"""Task Scheduler — checks due scheduled_tasks and sends alerts via LINE."""

import logging

log = logging.getLogger("synapse.assistant.scheduler")


async def check_due_tasks(pg, access_token: str | None = None, notify_user_id: str | None = None) -> list[dict]:
    """Check for due scheduled_tasks and create alert_log entries.

    If access_token and notify_user_id are provided, also sends LINE push notification.
    Returns list of alerts created.
    """
    due_tasks = await pg.get_due_tasks()
    alerts = []

    for task in due_tasks:
        task_id = task["id"]
        doc_id = task.get("doc_id")
        tag_name = task["tag_name"]
        title = task.get("title", "Untitled Task")
        due_date = task.get("due_date", "No due date")

        message = _format_alert_message(title, due_date, tag_name)

        # Create alert log entry
        alert = await pg.create_alert(
            task_id=task_id,
            doc_id=doc_id,
            tag_name=tag_name,
            channel="line",
            message=message,
        )
        alerts.append(alert)

        # Send LINE push if configured
        if access_token and notify_user_id:
            await _send_push(access_token, notify_user_id, message)

        # Mark task as alerted (prevents duplicate alerts)
        await pg.mark_task_alerted(task_id)

        log.info("Alert sent for task %s (doc=%s, tag=%s)", task_id, doc_id, tag_name)

    return alerts


def _format_alert_message(title: str, due_date: str | None, tag_name: str) -> str:
    """Format an alert message for LINE notification."""
    if due_date:
        return f"⏰ {title}\n\nกำหนด: {due_date}\nTag: #{tag_name}"
    return f"📋 {title}\n\nTag: #{tag_name}"


async def _send_push(access_token: str, user_id: str, text: str) -> None:
    """Send a push message via LINE Messaging API. Errors are logged, never raised."""
    import httpx

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": text}],
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            log.debug("LINE push sent to %s: %s", user_id, resp.status_code)
    except Exception as e:
        log.warning("LINE push failed (non-fatal): %s", e)
