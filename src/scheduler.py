"""Scheduled scanning + nightly reconcile — background tasks for synapse daemon."""

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from src.config import Settings
from src.db.pg_store import PgStore
from src.embed.ollama import OllamaEmbedder

log = logging.getLogger("synapse.scheduler")


class TaskScheduler:
    """Periodic task scheduler: scan + nightly reconcile + topic monitor."""

    def __init__(
        self,
        pg: PgStore,
        settings: Settings,
        embedder: OllamaEmbedder | None = None,
        scan_interval: int = 600,
        reconcile_hour: int = 2,
        topic_monitor_interval: int = 3600,
    ):
        self._pg = pg
        self._settings = settings
        self._embedder = embedder
        self._scan_interval = scan_interval
        self._reconcile_hour = reconcile_hour
        self._topic_monitor_interval = topic_monitor_interval
        self._scan_task: asyncio.Task | None = None
        self._reconcile_task: asyncio.Task | None = None
        self._topic_monitor_task: asyncio.Task | None = None
        self._alert_task: asyncio.Task | None = None
        self._running = False
        self._last_reconcile_date: str | None = None

    async def start(self) -> None:
        """Start scheduled tasks."""
        if self._running:
            return
        self._running = True

        if self._scan_interval > 0:
            self._scan_task = asyncio.create_task(self._scan_loop())
            log.info("Scan scheduler started (interval=%ds)", self._scan_interval)

        # reconcile_hour < 0 disables the nightly loop entirely (manual-only
        # mode — doctorboyz 3/10/26). Without this guard, replace(hour=-1)
        # would raise ValueError every loop iteration.
        if self._reconcile_hour >= 0:
            self._reconcile_task = asyncio.create_task(self._reconcile_loop())
            log.info("Reconcile scheduler started (daily at %02d:00)", self._reconcile_hour)
        else:
            log.info("Reconcile scheduler disabled (reconcile_hour=%d)", self._reconcile_hour)

        if self._topic_monitor_interval > 0:
            self._topic_monitor_task = asyncio.create_task(self._topic_monitor_loop())
            log.info("Topic monitor started (interval=%ds)", self._topic_monitor_interval)

        self._alert_task = asyncio.create_task(self._alert_loop())
        log.info("Assistant alert loop started (interval=5min)")

    async def stop(self) -> None:
        """Stop all scheduled tasks."""
        self._running = False
        for task in (self._scan_task, self._reconcile_task, self._topic_monitor_task, self._alert_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        log.info("Task scheduler stopped")

    async def _scan_loop(self) -> None:
        """Periodic scan loop."""
        while self._running:
            try:
                await self._scan_registered_projects()
            except Exception as e:
                log.error("Scan loop error: %s", e)

            try:
                await asyncio.sleep(self._scan_interval)
            except asyncio.CancelledError:
                break

    async def _reconcile_loop(self) -> None:
        """Daily reconcile loop — runs once per day at reconcile_hour."""
        while self._running:
            try:
                now = datetime.now()
                target = now.replace(hour=self._reconcile_hour, minute=0, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)

                sleep_seconds = (target - now).total_seconds()
                log.debug("Next reconcile in %.0f seconds (%s)", sleep_seconds, target.isoformat())

                await asyncio.sleep(sleep_seconds)

                if not self._running:
                    break

                today_str = datetime.now().strftime("%Y-%m-%d")
                if self._last_reconcile_date == today_str:
                    log.debug("Reconcile already ran today, skipping")
                    continue

                log.info("Starting nightly reconcile (hour=%02d:00)", self._reconcile_hour)
                await self._run_reconcile()
                self._last_reconcile_date = today_str
                log.info("Nightly reconcile completed")

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Reconcile loop error: %s", e)
                await asyncio.sleep(3600)  # Retry in 1 hour on error

    async def _scan_registered_projects(self) -> None:
        """Scan all registered projects for new files. Auto-writes updated docs
        back to Obsidian vaults after scanning."""
        from src.registry import list_projects
        from src.ingest.init_scan import init_scan

        projects = await list_projects(self._pg)
        if not projects:
            return

        for project in projects:
            path = project.get("project_path")
            scope = project.get("scope")
            if not path or not Path(path).exists():
                log.warning("Project path not found: %s", path)
                continue

            log.info("Scanning project %s at %s", scope, path)
            try:
                result = await init_scan(path=path, tags=[scope], dry_run=False)
                indexed = result.get("indexed", 0)
                dups = result.get("duplicates", 0)
                superseded = result.get("superseded", 0)
                if indexed > 0 or dups > 0 or superseded > 0:
                    log.info("Project %s: indexed=%d, duplicates=%d, superseded=%d",
                             scope, indexed, dups, superseded)

                # Auto-write updated docs back to Obsidian vault
                if superseded > 0 and self._is_obsidian_vault(path):
                    await self._auto_write_to_obsidian(result, path)
            except Exception as e:
                log.error("Failed to scan project %s: %s", scope, e)

    @staticmethod
    def _is_obsidian_vault(project_path: str) -> bool:
        """Check if a directory is an Obsidian vault."""
        return (Path(project_path) / ".obsidian").is_dir()

    async def _auto_write_to_obsidian(self, scan_result: dict, vault_path: str) -> None:
        """Write superseded docs back to Obsidian vault after scan."""
        from src.ingest.obsidian_writer import write_document_to_obsidian

        files = scan_result.get("files", [])
        superseded_files = [f for f in files if f.get("status") == "superseded"]
        if not superseded_files:
            return

        written = 0
        for f in superseded_files:
            doc_id = f.get("id")
            if not doc_id:
                continue
            try:
                result = await write_document_to_obsidian(self._pg, doc_id, vault_path)
                if "error" not in result:
                    written += 1
                else:
                    log.warning("Auto-write failed for %s: %s", doc_id, result["error"])
            except Exception as e:
                log.warning("Auto-write error for %s: %s", doc_id, e)

        if written > 0:
            log.info("Auto-wrote %d updated docs to Obsidian vault %s", written, vault_path)

    async def _run_reconcile(self) -> None:
        """Run reconcile across all scopes. Reports llm_errors as failure —
        a dead judge must surface as status=failed, not a silent zero."""
        from src.reconcile import reconcile

        log_entry = await self._pg.start_reconcile_log(scope=None, dry_run=False)
        log_id = log_entry["id"]

        try:
            result = await reconcile(
                pg=self._pg,
                embedder=self._embedder,
                settings=self._settings,
                scope=None,
                dry_run=False,
            )
            defrag = result.get("defrag", {})
            detox = result.get("detox", {})
            merged = defrag.get("merged_duplicates", 0)
            removed = defrag.get("removed_duplicates", 0)
            conflicts = detox.get("conflicts_found", 0)
            fixed = detox.get("conflicts_resolved", 0)
            llm_errors = detox.get("llm_errors", 0)
            actions = detox.get("actions", {})

            status = "completed"
            error_message = None
            if llm_errors > 0:
                status = "failed"
                error_message = (
                    f"LLM judge unavailable — {llm_errors} pair(s) skipped "
                    f"without analysis (actions: {actions})"
                )

            await self._pg.complete_reconcile_log(
                log_id=log_id,
                merged_duplicates=merged,
                removed_duplicates=removed,
                conflicts_found=conflicts,
                conflicts_resolved=fixed,
                status=status,
                error_message=error_message,
            )
            log.info(
                "Reconcile %s: defrag(merged=%s, removed=%s) "
                "detox(conflicts=%s, fixed=%s, llm_errors=%s) actions=%s",
                status, merged, removed, conflicts, fixed, llm_errors, actions,
            )
        except Exception as e:
            await self._pg.complete_reconcile_log(
                log_id=log_id,
                status="failed",
                error_message=str(e)[:500],
            )
            log.error("Reconcile failed: %s", e)

    async def _topic_monitor_loop(self) -> None:
        """Periodic topic monitor loop."""
        from src.connectors.topic_monitor import run_topic_monitor
        from src.connectors.web_search import WebSearchConnector
        from src.connectors.social_search import SocialSearchConnector
        from src.ingest.push import Push

        push = Push(self._pg, self._embedder)

        while self._running:
            try:
                log.info("Running topic monitor pass")
                stats = await run_topic_monitor(
                    self._pg,
                    push,
                    web_search=WebSearchConnector(self._settings),
                    social_search=SocialSearchConnector(self._settings),
                )
                log.info(
                    "Topic monitor pass complete: topics=%d found=%d indexed=%d dups=%d errors=%d",
                    stats.get("topics_checked", 0),
                    stats.get("results_found", 0),
                    stats.get("indexed", 0),
                    stats.get("duplicates", 0),
                    stats.get("errors", 0),
                )
            except Exception as e:
                log.error("Topic monitor loop error: %s", e)

            try:
                await asyncio.sleep(self._topic_monitor_interval)
            except asyncio.CancelledError:
                break

    async def topic_monitor_once(self) -> dict:
        """Run a single topic monitor pass (manual trigger)."""
        from src.connectors.topic_monitor import run_topic_monitor
        from src.connectors.web_search import WebSearchConnector
        from src.connectors.social_search import SocialSearchConnector
        from src.ingest.push import Push

        push = Push(self._pg, self._embedder)
        stats = await run_topic_monitor(
            self._pg,
            push,
            web_search=WebSearchConnector(self._settings),
            social_search=SocialSearchConnector(self._settings),
        )
        return stats

    async def _alert_loop(self) -> None:
        """Check for due scheduled_tasks every 5 minutes and send alerts."""
        from src.assistant.scheduler import check_due_tasks

        while self._running:
            try:
                access_token = self._settings.line_channel_access_token
                alerts = await check_due_tasks(self._pg, access_token=access_token)
                if alerts:
                    log.info("Alert loop: %d alerts sent", len(alerts))
            except Exception as e:
                log.error("Alert loop error: %s", e)

            try:
                await asyncio.sleep(300)  # 5 minutes
            except asyncio.CancelledError:
                break

    async def scan_once(self) -> dict:
        """Run a single scan of all registered projects (manual trigger).
        Auto-writes updated docs back to Obsidian vaults after scanning."""
        from src.registry import list_projects
        from src.ingest.init_scan import init_scan

        projects = await list_projects(self._pg)
        results = []
        for project in projects:
            path = project.get("project_path")
            scope = project.get("scope")
            if not path or not Path(path).exists():
                continue
            try:
                result = await init_scan(path=path, tags=[scope], dry_run=False)
                results.append({"scope": scope, "result": result})

                if result.get("superseded", 0) > 0 and self._is_obsidian_vault(path):
                    await self._auto_write_to_obsidian(result, path)
            except Exception as e:
                results.append({"scope": scope, "error": str(e)})
        return {"scanned_projects": len(projects), "results": results}
