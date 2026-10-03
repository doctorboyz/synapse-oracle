"""Tests for assistant scheduler — scheduled_tasks + alert_log CRUD."""

import pytest


@pytest.mark.asyncio
class TestScheduledTasksCRUD:
    async def test_create_scheduled_task(self, clean_pg):
        result = await clean_pg.create_scheduled_task(
            doc_id=None,
            tag_name="task",
            task_type="reminder",
            due_date="2026-12-31T23:59:59",
        )
        assert result["status"] == "created"
        assert result["id"] is not None

    async def test_create_task_with_doc(self, clean_pg):
        doc = await clean_pg.add(
            title="Test Doc", content="test content", doc_type="task", tags=["task"],
        )
        result = await clean_pg.create_scheduled_task(
            doc_id=doc["id"],
            tag_name="task",
            due_date="2026-12-31T23:59:59",
        )
        assert result["status"] == "created"

    async def test_create_duplicate_task_avoided(self, clean_pg):
        doc = await clean_pg.add(
            title="Dup Task Test", content="content", doc_type="task", tags=["task"],
        )
        first = await clean_pg.create_scheduled_task(
            doc_id=doc["id"], tag_name="task",
        )
        second = await clean_pg.create_scheduled_task(
            doc_id=doc["id"], tag_name="task",
        )
        assert first["status"] == "created"
        assert second["status"] == "exists"
        assert second["id"] == first["id"]

    async def test_get_due_tasks(self, clean_pg):
        # Create a task due now
        await clean_pg.create_scheduled_task(
            doc_id=None,
            tag_name="task",
            due_date="2020-01-01T00:00:00",  # Past date
            alert_before="1 hour",
        )
        tasks = await clean_pg.get_due_tasks()
        assert len(tasks) > 0
        assert tasks[0]["tag_name"] == "task"

    async def test_get_due_tasks_excludes_future(self, clean_pg):
        await clean_pg.create_scheduled_task(
            doc_id=None,
            tag_name="reminder",
            due_date="2099-12-31T23:59:59",  # Far future
            alert_before="1 hour",
        )
        tasks = await clean_pg.get_due_tasks()
        # Should not include far future task
        future_tasks = [t for t in tasks if t["tag_name"] == "reminder"]
        assert len(future_tasks) == 0

    async def test_mark_task_alerted(self, clean_pg):
        await clean_pg.create_scheduled_task(
            doc_id=None,
            tag_name="task",
            due_date="2020-01-01T00:00:00",
            alert_before="1 hour",
        )
        tasks = await clean_pg.get_due_tasks()
        assert len(tasks) > 0

        await clean_pg.mark_task_alerted(tasks[0]["id"])
        # Should not appear again immediately
        tasks2 = await clean_pg.get_due_tasks()
        remaining = [t for t in tasks2 if t["id"] == tasks[0]["id"]]
        assert len(remaining) == 0

    async def test_resolve_task(self, clean_pg):
        result = await clean_pg.create_scheduled_task(
            doc_id=None, tag_name="task",
        )
        resolved = await clean_pg.resolve_task(result["id"])
        assert resolved  # truthy int (1 row updated)

        tasks = await clean_pg.list_scheduled_tasks(status="pending")
        resolved_ids = [t["id"] for t in tasks]
        assert result["id"] not in resolved_ids

    async def test_list_scheduled_tasks_by_tag(self, clean_pg):
        await clean_pg.create_scheduled_task(doc_id=None, tag_name="task")
        await clean_pg.create_scheduled_task(doc_id=None, tag_name="reminder")
        await clean_pg.create_scheduled_task(doc_id=None, tag_name="event")

        tasks = await clean_pg.list_scheduled_tasks(tag_name="task")
        assert all(t["tag_name"] == "task" for t in tasks)


@pytest.mark.asyncio
class TestAlertLogCRUD:
    async def test_create_alert(self, clean_pg):
        alert = await clean_pg.create_alert(
            task_id=None,
            doc_id=None,
            tag_name="task",
            channel="line",
            message="Test alert",
        )
        assert alert["id"] is not None
        assert alert["sent_at"] is not None

    async def test_create_alert_with_task(self, clean_pg):
        task = await clean_pg.create_scheduled_task(
            doc_id=None, tag_name="task",
        )
        doc = await clean_pg.add(
            title="Alert Doc", content="alert test", doc_type="task", tags=["task"],
        )

        alert = await clean_pg.create_alert(
            task_id=task["id"],
            doc_id=doc["id"],
            tag_name="task",
            channel="line",
            message="Due task alert",
        )
        assert alert["id"] is not None

    async def test_get_recent_alerts(self, clean_pg):
        for i in range(3):
            await clean_pg.create_alert(
                task_id=None, doc_id=None,
                tag_name="task", channel="line",
                message=f"Alert {i}",
            )
        alerts = await clean_pg.get_recent_alerts(limit=10)
        assert len(alerts) >= 3
