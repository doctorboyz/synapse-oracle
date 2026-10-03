"""Tag Rules Engine — applies tag_rules when documents are stored.

When a document is tagged, matching rules fire:
  - auto_classify + handler="task" → creates scheduled_tasks entry
  - alert_on_due → task will be picked up by scheduler for LINE notification
  - collect_related → searches for related docs by same tag (future)
"""

import logging

log = logging.getLogger("synapse.assistant.tag_rules")


# ─── Default rules seeded on first run ───

DEFAULT_RULES = [
    {
        "tag_name": "task",
        "handler": "task",
        "description": "Convert tagged documents into scheduled tasks with due dates",
        "auto_classify": True,
        "alert_on_due": True,
    },
    {
        "tag_name": "reminder",
        "handler": "task",
        "description": "One-time reminders — alert at due time",
        "auto_classify": True,
        "alert_on_due": True,
    },
    {
        "tag_name": "event",
        "handler": "calendar",
        "description": "Calendar events with date awareness",
        "auto_classify": True,
        "alert_on_due": True,
    },
]


async def seed_default_rules(pg) -> None:
    """Ensure default tag rules exist. Always upserts — restores defaults on restart."""
    for rule in DEFAULT_RULES:
        await pg.upsert_tag_rule(**rule)
    log.info("Seeded %d default tag rules", len(DEFAULT_RULES))


async def apply_tag_rules(pg, doc_id: str, tags: list[str], content: str = "") -> list[dict]:
    """Apply matching tag rules after a document is stored.

    Returns list of actions taken (e.g. created scheduled tasks).
    """
    actions = []

    for tag_name in tags:
        rule = await pg.get_tag_rule(tag_name)
        if not rule or not rule.get("enabled"):
            continue

        handler = rule.get("handler", "")
        auto_classify = rule.get("auto_classify", False)
        alert_on_due = rule.get("alert_on_due", False)

        if auto_classify and handler == "task":
            task_info = _extract_task_info_from_content(content) if content else {}
            due_date = task_info.get("due_date")
            priority = task_info.get("priority", "medium")

            result = await pg.create_scheduled_task(
                doc_id=doc_id,
                tag_name=tag_name,
                task_type="reminder",
                due_date=due_date,
                metadata={"priority": priority, "rule_id": str(rule["id"])},
            )
            actions.append({
                "rule": tag_name,
                "action": "create_task",
                "task_id": result.get("id"),
                "status": result.get("status"),
                "due_date": due_date,
            })
            log.info(
                "Tag rule %s → scheduled task %s (due=%s)",
                tag_name, result.get("id"), due_date,
            )

    return actions


def _extract_task_info_from_content(text: str) -> dict:
    """Extract task metadata from content text.

    Reuses the same detection logic as line_handler._extract_task_info()
    but as a standalone function so the assistant layer doesn't depend on line_handler.
    """
    import re

    result = {"is_task": False, "due_date": None, "priority": "medium", "assignee": None}

    # Date patterns
    date_patterns = [
        (r"(?:within|in|ภายใน)\s+(\d+)\s*(?:day|days|วัน)", "relative_days"),
        (r"due[:\s]+(\d{4}-\d{2}-\d{2})", "iso_date"),
        (r"due[:\s]+(\d{2}/\d{2}/\d{4})", "thai_date"),
        (r"(?:ภายใน|ก่อน|due|ก่อนวันที่)[:\s]*(\d{1,2})\s*(ม\.?ค\.?|ก\.?พ\.?|มี\.?ค\.?|เม\.?ย\.?|พ\.?ค\.?|มิ\.?ย\.?|ก\.?ค\.?|ส\.?ค\.?|ก\.?ย\.?|ต\.?ค\.?|พ\.?ย\.?|ธ\.?ค\.?)", "thai_month"),
        (r"(?:tomorrow|พรุ่งนี้)", "tomorrow"),
        (r"(?:today|วันนี้)", "today"),
        (r"(?:next week|อาทิตย์หน้า|สัปดาห์หน้า)", "next_week"),
        (r"(วันจันทร์|วันอังคาร|วันพุธ|วันพฤหัสบดี|วันพฤหัส|วันศุกร์|วันเสาร์|วันอาทิตย์)(นี้|หน้า)?", "thai_weekday"),
    ]

    for pattern, kind in date_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            from datetime import datetime, timedelta

            now = datetime.now()
            if kind == "relative_days":
                days = int(m.group(1))
                result["due_date"] = (now + timedelta(days=days)).strftime("%Y-%m-%dT23:59:59")
            elif kind == "iso_date":
                result["due_date"] = f"{m.group(1)}T23:59:59"
            elif kind == "tomorrow":
                result["due_date"] = (now + timedelta(days=1)).strftime("%Y-%m-%dT23:59:59")
            elif kind == "today":
                result["due_date"] = now.strftime("%Y-%m-%dT23:59:59")
            elif kind == "next_week":
                result["due_date"] = (now + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59")
            elif kind == "thai_weekday":
                _THAI_WDAY = {
                    "วันจันทร์": 0, "วันอังคาร": 1, "วันพุธ": 2, "วันพฤหัสบดี": 3,
                    "วันพฤหัส": 3, "วันศุกร์": 4, "วันเสาร์": 5, "วันอาทิตย์": 6,
                }
                target_wday = _THAI_WDAY[m.group(1)]
                modifier = m.group(2)
                today_wday = now.weekday()
                days_ahead = (target_wday - today_wday) % 7
                if days_ahead == 0:
                    days_ahead = 7
                if modifier == "หน้า":
                    days_ahead += 7
                result["due_date"] = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%dT23:59:59")
            break

    # Priority
    if re.search(r"(urgent|ด่วน|asap|critical)", text, re.IGNORECASE):
        result["priority"] = "high"
    elif re.search(r"(low|ต่ำ|nice.to.have)", text, re.IGNORECASE):
        result["priority"] = "low"

    result["is_task"] = True
    return result
