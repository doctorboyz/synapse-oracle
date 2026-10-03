"""Tests for scheduler — TaskScheduler start/stop, loops, and manual triggers."""

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.scheduler import TaskScheduler


class TestTaskSchedulerInit:
    def test_init_defaults(self):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings)
        assert sched._pg is pg
        assert sched._settings is settings
        assert sched._scan_interval == 600
        assert sched._reconcile_hour == 2
        assert sched._topic_monitor_interval == 3600
        assert sched._running is False
        assert sched._scan_task is None

    def test_init_custom_intervals(self):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings, scan_interval=300, reconcile_hour=4, topic_monitor_interval=0)
        assert sched._scan_interval == 300
        assert sched._reconcile_hour == 4
        assert sched._topic_monitor_interval == 0


class TestTaskSchedulerStartStop:
    @pytest.mark.asyncio
    async def test_start_creates_tasks(self):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings)

        await sched.start()

        assert sched._running is True
        assert sched._scan_task is not None
        assert sched._reconcile_task is not None
        assert sched._topic_monitor_task is not None

        await sched.stop()

    @pytest.mark.asyncio
    async def test_start_negative_reconcile_hour_disables_loop(self):
        """SYNAPSE_RECONCILE_HOUR < 0 must disable the nightly loop entirely —
        no task, no crash from replace(hour=-1) (doctorboyz 3/10/26: manual only)."""
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings, reconcile_hour=-1)

        await sched.start()

        assert sched._running is True
        assert sched._reconcile_task is None

        await sched.stop()

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings)
        await sched.start()
        first_scan = sched._scan_task

        await sched.start()

        assert sched._scan_task is first_scan
        await sched.stop()

    @pytest.mark.asyncio
    async def test_start_no_scan_when_interval_zero(self):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings, scan_interval=0)

        await sched.start()

        assert sched._scan_task is None
        assert sched._reconcile_task is not None
        await sched.stop()

    @pytest.mark.asyncio
    async def test_start_no_topic_when_interval_zero(self):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings, topic_monitor_interval=0)

        await sched.start()

        assert sched._topic_monitor_task is None
        assert sched._reconcile_task is not None
        await sched.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings)
        await sched.start()

        await sched.stop()

        assert sched._running is False
        for task in (sched._scan_task, sched._reconcile_task, sched._topic_monitor_task):
            if task is not None:
                assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_stop_idempotent(self):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings)
        # stop without start should not raise
        await sched.stop()


class TestScanLoop:
    @pytest.mark.asyncio
    async def test_scan_loop_runs_then_breaks_on_cancel(self, monkeypatch):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings, scan_interval=600)
        sched._running = True

        scan_calls = []

        async def fake_scan():
            scan_calls.append(1)
            sched._running = False

        monkeypatch.setattr(sched, "_scan_registered_projects", fake_scan)
        monkeypatch.setattr(asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))

        await sched._scan_loop()

        assert len(scan_calls) == 1

    @pytest.mark.asyncio
    async def test_scan_loop_handles_scan_error(self, monkeypatch):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings, scan_interval=600)
        sched._running = True

        call_count = 0

        async def fake_scan():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("scan failed")
            sched._running = False

        monkeypatch.setattr(sched, "_scan_registered_projects", fake_scan)
        monkeypatch.setattr(asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))

        await sched._scan_loop()

        # After scan error, sleep is called and raises CancelledError -> break
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_scan_loop_breaks_on_sleep_cancel(self, monkeypatch):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings, scan_interval=600)
        sched._running = True

        async def fake_scan():
            pass

        monkeypatch.setattr(sched, "_scan_registered_projects", fake_scan)

        sleep_calls = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)
            raise asyncio.CancelledError()

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        await sched._scan_loop()

        assert len(sleep_calls) == 1
        assert sleep_calls[0] == 600


class TestReconcileLoop:
    @pytest.mark.asyncio
    async def test_reconcile_runs_once_then_breaks(self, monkeypatch):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings, reconcile_hour=2)
        sched._running = True

        reconcile_calls = []

        async def fake_reconcile():
            reconcile_calls.append(1)
            sched._running = False

        monkeypatch.setattr(sched, "_run_reconcile", fake_reconcile)
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())

        await sched._reconcile_loop()

        assert len(reconcile_calls) == 1
        assert sched._last_reconcile_date == datetime.now().strftime("%Y-%m-%d")

    @pytest.mark.asyncio
    async def test_reconcile_skips_if_already_ran_today(self, monkeypatch):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings, reconcile_hour=2)
        sched._running = True
        sched._last_reconcile_date = datetime.now().strftime("%Y-%m-%d")

        reconcile_calls = []

        async def fake_reconcile():
            reconcile_calls.append(1)
            sched._running = False

        monkeypatch.setattr(sched, "_run_reconcile", fake_reconcile)

        sleep_count = 0

        async def fake_sleep(seconds):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                sched._running = False
                raise asyncio.CancelledError()

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        await sched._reconcile_loop()

        assert len(reconcile_calls) == 0

    @pytest.mark.asyncio
    async def test_reconcile_handles_error_then_retries(self, monkeypatch):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings, reconcile_hour=2)
        sched._running = True

        call_count = 0

        async def fake_reconcile():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("reconcile failed")
            sched._running = False

        monkeypatch.setattr(sched, "_run_reconcile", fake_reconcile)
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())

        await sched._reconcile_loop()

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_reconcile_breaks_on_cancel(self, monkeypatch):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings, reconcile_hour=2)
        sched._running = True

        monkeypatch.setattr(sched, "_run_reconcile", AsyncMock())
        monkeypatch.setattr(asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))

        await sched._reconcile_loop()


class TestScanRegisteredProjects:
    @pytest.mark.asyncio
    async def test_scans_each_project(self, monkeypatch, tmp_path):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings)

        p1 = tmp_path / "s1"
        p2 = tmp_path / "s2"
        p1.mkdir()
        p2.mkdir()

        projects = [
            {"scope": "s1", "project_path": str(p1)},
            {"scope": "s2", "project_path": str(p2)},
        ]

        with patch("src.registry.list_projects", new_callable=AsyncMock, return_value=projects):
            scan_results = []

            async def fake_init_scan(path, tags=None, dry_run=False):
                scan_results.append({"path": path, "tags": tags})
                return {"indexed": 1, "duplicates": 0}

            with patch("src.ingest.init_scan.init_scan", new_callable=AsyncMock, side_effect=fake_init_scan):
                await sched._scan_registered_projects()

            assert len(scan_results) == 2

    @pytest.mark.asyncio
    async def test_skips_missing_project_path(self, monkeypatch):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings)

        projects = [
            {"scope": "s1", "project_path": "/nonexistent/path"},
        ]

        with patch("src.registry.list_projects", new_callable=AsyncMock, return_value=projects):
            scan_results = []

            async def fake_init_scan(path, tags=None, dry_run=False):
                scan_results.append(scope)
                return {"indexed": 1}

            with patch("src.ingest.init_scan.init_scan", new_callable=AsyncMock, side_effect=fake_init_scan):
                await sched._scan_registered_projects()

            assert len(scan_results) == 0

    @pytest.mark.asyncio
    async def test_skips_none_path(self, monkeypatch):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings)

        projects = [{"scope": "s1", "project_path": None}]

        with patch("src.registry.list_projects", new_callable=AsyncMock, return_value=projects):
            await sched._scan_registered_projects()

    @pytest.mark.asyncio
    async def test_handles_init_scan_error(self, monkeypatch):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings)

        projects = [{"scope": "s1", "project_path": "/tmp"}]

        with patch("src.registry.list_projects", new_callable=AsyncMock, return_value=projects):
            async def fake_init_scan(path, tags=None, dry_run=False):
                raise RuntimeError("scan error")

            with patch("src.ingest.init_scan.init_scan", new_callable=AsyncMock, side_effect=fake_init_scan):
                # should not raise
                await sched._scan_registered_projects()

    @pytest.mark.asyncio
    async def test_no_projects_returns_early(self, monkeypatch):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings)

        with patch("src.registry.list_projects", new_callable=AsyncMock, return_value=[]):
            await sched._scan_registered_projects()


class TestRunReconcile:
    @pytest.mark.asyncio
    async def test_run_reconcile_success(self, monkeypatch):
        pg = MagicMock()
        pg.start_reconcile_log = AsyncMock(return_value={"id": "log-123"})
        pg.complete_reconcile_log = AsyncMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings)

        async def fake_reconcile(**kwargs):
            return {
                "defrag": {"merged_duplicates": 2, "removed_duplicates": 1},
                "detox": {"conflicts_found": 3, "conflicts_resolved": 2},
            }

        monkeypatch.setattr("src.reconcile.reconcile", fake_reconcile)

        await sched._run_reconcile()

        pg.start_reconcile_log.assert_called_once()
        pg.complete_reconcile_log.assert_called_once()
        call_kwargs = pg.complete_reconcile_log.call_args.kwargs
        assert call_kwargs["log_id"] == "log-123"
        assert call_kwargs["merged_duplicates"] == 2
        assert call_kwargs["removed_duplicates"] == 1
        assert call_kwargs["conflicts_found"] == 3
        assert call_kwargs["conflicts_resolved"] == 2
        assert call_kwargs["status"] == "completed"
        assert call_kwargs["error_message"] is None

    @pytest.mark.asyncio
    async def test_run_reconcile_llm_errors_marks_failed(self, monkeypatch):
        """A dead judge must surface as status=failed, not a silent completed zero."""
        pg = MagicMock()
        pg.start_reconcile_log = AsyncMock(return_value={"id": "log-789"})
        pg.complete_reconcile_log = AsyncMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings)

        async def fake_reconcile(**kwargs):
            return {
                "defrag": {"merged_duplicates": 0, "removed_duplicates": 0},
                "detox": {
                    "conflicts_found": 0,
                    "conflicts_resolved": 0,
                    "llm_errors": 5,
                    "actions": {"merged": 0, "stale_cut": 0, "conflict_open": 0},
                },
            }

        monkeypatch.setattr("src.reconcile.reconcile", fake_reconcile)

        await sched._run_reconcile()

        call_kwargs = pg.complete_reconcile_log.call_args.kwargs
        assert call_kwargs["status"] == "failed"
        assert "LLM judge unavailable" in call_kwargs["error_message"]
        assert "5 pair" in call_kwargs["error_message"]

    @pytest.mark.asyncio
    async def test_run_reconcile_failure(self, monkeypatch):
        pg = MagicMock()
        pg.start_reconcile_log = AsyncMock(return_value={"id": "log-456"})
        pg.complete_reconcile_log = AsyncMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings)

        async def fake_reconcile(**kwargs):
            raise RuntimeError("reconcile crashed")

        monkeypatch.setattr("src.reconcile.reconcile", fake_reconcile)

        await sched._run_reconcile()

        pg.complete_reconcile_log.assert_called_once()
        call_kwargs = pg.complete_reconcile_log.call_args.kwargs
        assert call_kwargs["log_id"] == "log-456"
        assert call_kwargs["status"] == "failed"
        assert "reconcile crashed" in call_kwargs["error_message"]


class TestManualTriggers:
    @pytest.mark.asyncio
    async def test_scan_once(self, monkeypatch, tmp_path):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings)

        p1 = tmp_path / "s1"
        p1.mkdir()

        projects = [
            {"scope": "s1", "project_path": str(p1)},
        ]

        with patch("src.registry.list_projects", new_callable=AsyncMock, return_value=projects):
            async def fake_init_scan(path, tags=None, dry_run=False):
                return {"indexed": 2}

            with patch("src.ingest.init_scan.init_scan", new_callable=AsyncMock, side_effect=fake_init_scan):
                result = await sched.scan_once()

            assert result["scanned_projects"] == 1
            assert result["results"][0]["scope"] == "s1"

    @pytest.mark.asyncio
    async def test_topic_monitor_once(self, monkeypatch):
        pg = MagicMock()
        settings = MagicMock()
        embedder = MagicMock()
        sched = TaskScheduler(pg, settings, embedder=embedder)

        async def fake_run_topic_monitor(pg, push, web_search, social_search):
            return {"topics_checked": 5, "indexed": 3}

        with patch("src.connectors.topic_monitor.run_topic_monitor", new_callable=AsyncMock, side_effect=fake_run_topic_monitor):
            with patch("src.connectors.web_search.WebSearchConnector", return_value=MagicMock()):
                with patch("src.connectors.social_search.SocialSearchConnector", return_value=MagicMock()):
                    result = await sched.topic_monitor_once()

        assert result["topics_checked"] == 5
        assert result["indexed"] == 3

    @pytest.mark.asyncio
    async def test_scan_once_skips_missing_path(self, monkeypatch):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings)

        projects = [
            {"scope": "s1", "project_path": "/nonexistent/path"},
        ]

        with patch("src.registry.list_projects", new_callable=AsyncMock, return_value=projects):
            result = await sched.scan_once()
            assert result["scanned_projects"] == 1
            assert len(result["results"]) == 0

    @pytest.mark.asyncio
    async def test_scan_once_handles_init_scan_error(self, monkeypatch):
        pg = MagicMock()
        settings = MagicMock()
        sched = TaskScheduler(pg, settings)

        projects = [{"scope": "s1", "project_path": "/tmp"}]

        with patch("src.registry.list_projects", new_callable=AsyncMock, return_value=projects):
            async def fake_init_scan(path, tags=None, dry_run=False):
                raise RuntimeError("scan error")

            with patch("src.ingest.init_scan.init_scan", new_callable=AsyncMock, side_effect=fake_init_scan):
                result = await sched.scan_once()

            assert result["results"][0]["error"] == "scan error"


class TestTopicMonitorLoop:
    @pytest.mark.asyncio
    async def test_topic_monitor_loop_runs_then_breaks(self, monkeypatch):
        pg = MagicMock()
        settings = MagicMock()
        embedder = MagicMock()
        sched = TaskScheduler(pg, settings, embedder=embedder, topic_monitor_interval=3600)
        sched._running = True

        call_count = 0

        async def fake_run_topic_monitor(pg, push, web_search, social_search):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                sched._running = False
            return {"topics_checked": 1}

        with patch("src.connectors.topic_monitor.run_topic_monitor", new_callable=AsyncMock, side_effect=fake_run_topic_monitor):
            with patch("src.connectors.web_search.WebSearchConnector", return_value=MagicMock()):
                with patch("src.connectors.social_search.SocialSearchConnector", return_value=MagicMock()):
                    monkeypatch.setattr(asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))
                    await sched._topic_monitor_loop()

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_topic_monitor_loop_handles_error(self, monkeypatch):
        pg = MagicMock()
        settings = MagicMock()
        embedder = MagicMock()
        sched = TaskScheduler(pg, settings, embedder=embedder, topic_monitor_interval=3600)
        sched._running = True

        call_count = 0

        async def fake_run_topic_monitor(pg, push, web_search, social_search):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("topic error")
            sched._running = False

        sleep_count = 0

        async def fake_sleep(seconds):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                raise asyncio.CancelledError()

        with patch("src.connectors.topic_monitor.run_topic_monitor", new_callable=AsyncMock, side_effect=fake_run_topic_monitor):
            with patch("src.connectors.web_search.WebSearchConnector", return_value=MagicMock()):
                with patch("src.connectors.social_search.SocialSearchConnector", return_value=MagicMock()):
                    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
                    await sched._topic_monitor_loop()

        assert call_count == 2
