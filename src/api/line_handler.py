"""LINE webhook handler — auto-ingest pipeline: full text, OCR, dedup.

All messages (group/room AND DM) go directly to knowledge store as "note" type.
No pending reviews, no confirmation flow.

Task creation requires explicit intent via /task, /todo, or /remind commands.
Regular messages with dates, @mentions, or task-like words are stored as notes,
NOT auto-classified as tasks. This prevents false positives where casual
messages get incorrectly tagged as tasks and trigger supersede logic.

Commands: /search, /ask, /recent, /stats, /tags, /task, /todo, /remind, /help
"""

import base64
import hashlib
import hmac
import logging
import re
import sys
from datetime import datetime, timedelta


log = logging.getLogger("synapse.line")
log.setLevel(logging.DEBUG)
if not log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
    log.addHandler(_h)
    log.propagate = False

# ─── Confirmation keywords (kept for backward compat, not used) ──
CONFIRM_YES = {"yes", "y", "ใช่", "yes", "ok", "okay", "ตกลง", "บันทึก", "save", "confirm"}
CONFIRM_NO = {"no", "n", "ไม่", "cancel", "ยกเลิก", "ลบ", "delete", "skip"}
CONFIRM_EDIT = {"edit", "แก้ไข", "เปลี่ยน", "change", "fix"}

# ─── Question detection ─────────────────────────────────────────
QUESTION_WORDS_EN = {
    "who", "what", "where", "when", "why", "how", "which", "whose",
    "is there", "are there", "do you", "can you", "could you",
    "tell me", "explain", "what is", "how to", "how do",
    "find", "search", "look for", "tell me about",
}
QUESTION_WORDS_TH = {
    "มีไหม", "คืออะไร", "อย่างไร", "ยังไง", "ทำไม", "ใคร", "ที่ไหน",
    "อยู่ไหน", "ช่วยหา", "บอกหน่อย", "อธิบายหน่อย", "สอนหน่อย",
    "เท่าไร", "เมื่อไหร่", "ได้ไหม", "ได้มั้ย", "รู้ไหม", "คือยังไง",
}
QUESTION_MARKS = {"?", "?", "？"}

# ─── Commands ───────────────────────────────────────────────────
COMMANDS = {"search", "recent", "stats", "scopes", "tags", "help", "ask", "task", "todo", "remind"}

# ─── Markdown stripping for LINE (LINE doesn't render markdown) ──

def _strip_markdown(text: str) -> str:
    """Remove markdown formatting from text for LINE plain-text replies.

    LINE Messaging API doesn't render markdown. LLM responses often
    contain **bold**, ## headers, - bullets, > quotes, etc. that look
    ugly as raw text in LINE chats. This function converts them to
    plain text with Unicode/emoji alternatives.
    """
    import re

    # Headers: ## Header → 📌 Header (or just text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # Bold: **text** or __text__ → text
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)

    # Italic: *text* or _text_ → text (careful not to strip Thai underscores)
    text = re.sub(r'(?<!\w)\*(.+?)\*(?!\w)', r'\1', text)
    # Only strip _emphasis_ when surrounded by spaces (not Thai text)
    text = re.sub(r'(?<=\s)_(.+?)_(?=\s)', r'\1', text)

    # Strikethrough: ~~text~~ → text
    text = re.sub(r'~~(.+?)~~', r'\1', text)

    # Blockquotes: > text → text
    text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)

    # Unordered list markers: - item or * item → • item
    text = re.sub(r'^[\-\*]\s+', '• ', text, flags=re.MULTILINE)

    # Ordered list markers: 1. item → 1. item (already fine, but normalize)
    # No change needed for numbered lists

    # Code blocks: ```lang\ncode\n``` → code (remove fences)
    text = re.sub(r'```\w*\n?', '', text)
    text = re.sub(r'```', '', text)

    # Inline code: `code` → code
    text = re.sub(r'`(.+?)`', r'\1', text)

    # Links: [text](url) → text
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)

    # Images: ![alt](url) → (image)
    text = re.sub(r'!\[.*?\]\(.+?\)', '(image)', text)

    # Horizontal rules: --- or *** or ___ → (blank line, already fine)
    text = re.sub(r'^[-*_]{3,}$', '', text, flags=re.MULTILINE)

    # Collapse multiple blank lines to max 2
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


# ─── Source formatting ──────────────────────────────────────────

def _format_source_line(index: int, doc: dict) -> str:
    """Build a human-readable source line from a search result doc."""
    title = doc.get('title', 'Untitled')
    doctype = doc.get('doc_type', '')
    oracle = doc.get('oracle_name', '')
    sp = doc.get('source_project', '')
    scope = doc.get('scope', '')
    tags = doc.get('tags', [])

    parts = [f"  {index}. {title}"]
    meta_parts = []
    if doctype:
        meta_parts.append(doctype)
    if oracle:
        meta_parts.append(oracle)
    if sp and sp != oracle:
        meta_parts.append(sp)
    if meta_parts:
        parts.append(f"[{' · '.join(meta_parts)}]")
    if scope:
        parts.append(f"({scope})")
    # Show tags except internal/ID tags
    display_tags = [t for t in tags
                    if not t.startswith("line-") and t not in ("text", "image", "video", "audio", "file", "user", "group", "room")]
    if display_tags:
        parts.append(" ".join(f"#{t}" for t in display_tags[:5]))
    return " ".join(parts)


def _format_source_context(i: int, doc: dict) -> str:
    """Build context entry for LLM with metadata."""
    title = doc.get('title', 'Untitled')
    doctype = doc.get('doc_type', '')
    oracle = doc.get('oracle_name', '')
    sp = doc.get('source_project', '')
    scope = doc.get('scope', '')
    tags = doc.get('tags', [])
    snippet = doc.get('content', '')[:500]

    src_label = doctype if doctype else ""
    if oracle:
        src_label += f" · {oracle}"
    if sp and sp != oracle:
        src_label += f" · {sp}"
    display_tags = [t for t in tags
                    if not t.startswith("line-") and t not in ("text", "image", "video", "audio", "file", "user", "group", "room")]
    tag_label = f" #{' #'.join(display_tags[:5])}" if display_tags else ""
    return f"[{i}] {title} ({src_label} | scope: {scope}{tag_label}):\n{snippet}"


# ─── Task detection patterns ────────────────────────────────────
TASK_STATUS_EN = {"pending", "in progress", "done", "completed", "cancelled", "blocked", "waiting"}
TASK_STATUS_TH = {"รอ", "กำลังทำ", "เสร็จแล้ว", "ยกเลิก", "ดำเนินการ", "รอดำเนินการ"}
TASK_PRIORITY = {"urgent", "ด่วน", "high", "สูง", "medium", "กลาง", "low", "ต่ำ"}


def verify_line_signature(body: bytes, signature: str, channel_secret: str) -> bool:
    """Verify LINE webhook signature using HMAC-SHA256."""
    if not channel_secret:
        return False
    expected = base64.b64encode(
        hmac.new(
            channel_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def _is_command(text: str) -> tuple[str, str] | None:
    """Check if text is a bot command. Returns (cmd, args) or None."""
    text = text.strip()
    if not text.startswith("/"):
        return None
    parts = text[1:].split(None, 1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    if cmd in COMMANDS:
        return (cmd, args)
    return None


def _is_question(text: str) -> bool:
    """Detect whether text is clearly a question."""
    stripped = text.strip()
    lower = stripped.lower()
    if stripped[-1:] in QUESTION_MARKS:
        return True
    for word in QUESTION_WORDS_EN:
        if lower.startswith(word + " ") or lower == word:
            return True
    for word in QUESTION_WORDS_TH:
        if lower.startswith(word) or f" {word}" in lower:
            return True
    if re.search(r"(อยากรู้|อยากทราบ|ช่วย(บอก|หา|สอน))", lower):
        return True
    return False


def _extract_task_info(text: str, require_intent: bool = True) -> dict | None:
    """Parse task metadata from text. Returns dict or None if not a task.

    Args:
        text: The message text to parse.
        require_intent: If True (default), only classify as task when explicit
            task intent keywords are present (ต้องทำ, task, todo, etc.).
            If False, use the old aggressive detection that also matches
            dates and @mentions alone. Used only for /task /todo /remind commands
            where the user's intent to create a task is explicit.
    """
    lower = text.lower()
    task = {"is_task": False, "due_date": None, "status": None, "assignee": None, "priority": None}

    # --- Intent detection: explicit task markers ---
    INTENT_KEYWORDS_EN = {"task", "todo", "to-do", "to do", "reminder", "remind", "deadline", "action item", "follow up", "must", "need to", "have to", "going to"}
    INTENT_KEYWORDS_TH = {"ต้องทำ", "งานที่ต้อง", "เตือน", "เตือนความจำ", "กำหนด", "ภายใน", "อย่าลืม", "อย่าลืมว่า", "ต้องส่ง", "ต้องไป", "ต้องการให้", "มีนัด", "นัดหมาย"}
    has_intent = any(kw in lower for kw in INTENT_KEYWORDS_EN) or any(kw in lower for kw in INTENT_KEYWORDS_TH)

    # When require_intent=True, skip if no explicit task intent
    if require_intent and not has_intent:
        # Also check for @assignee without intent — NOT a task
        # Also check for bare dates without intent — NOT a task
        return None

    # Intent detected: this is a task even without specific dates/status
    if has_intent and not task["is_task"]:
        task["is_task"] = True

    # --- Due date detection ---
    thai_date_match = re.search(
        r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\s*(?:พ\.ศ\.?|ค\.ศ\.?)?",
        text,
    )
    if thai_date_match:
        day, month, year = thai_date_match.groups()
        if year:
            year_int = int(year)
            if year_int > 2500:
                year_int -= 543
            elif year_int < 100:
                year_int += 2000
        else:
            year_int = datetime.now().year
        try:
            task["due_date"] = f"{year_int:04d}-{int(month):02d}-{int(day):02d}"
            task["is_task"] = True
        except ValueError:
            pass

    # Relative dates
    if re.search(r"(due|deadline|ภายใน|กำหนด|duedate)\s*(วันนี้|today)", lower):
        task["due_date"] = datetime.now().strftime("%Y-%m-%d")
        task["is_task"] = True
    elif re.search(r"(due|deadline|ภายใน|กำหนด)\s*(พรุ่งนี้|tomorrow)", lower):
        task["due_date"] = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        task["is_task"] = True
    elif re.search(r"(due|deadline|ภายใน|กำหนด)\s*(สัปดาห์หน้า|next week)", lower):
        task["due_date"] = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        task["is_task"] = True

    # Thai weekday: วันศุกร์นี้, วันจันทร์หน้า, วันอังคาร
    _THAI_WEEKDAYS = {
        "วันจันทร์": 0, "วันอังคาร": 1, "วันพุธ": 2, "วันพฤหัสบดี": 3,
        "วันพฤหัส": 3, "วันศุกร์": 4, "วันเสาร์": 5, "วันอาทิตย์": 6,
    }
    thai_weekday_match = re.search(
        r"(วันจันทร์|วันอังคาร|วันพุธ|วันพฤหัสบดี|วันพฤหัส|วันศุกร์|วันเสาร์|วันอาทิตย์)(นี้|หน้า)?",
        text,
    )
    if thai_weekday_match:
        weekday_name = thai_weekday_match.group(1)
        modifier = thai_weekday_match.group(2)
        target_wday = _THAI_WEEKDAYS[weekday_name]
        today = datetime.now()
        today_wday = today.weekday()
        days_ahead = (target_wday - today_wday) % 7
        if days_ahead == 0:
            days_ahead = 7  # same day → next week
        if modifier == "หน้า":
            days_ahead += 7
        task["due_date"] = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        task["is_task"] = True

    # ISO date
    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if iso_match:
        task["due_date"] = iso_match.group(1)
        task["is_task"] = True

    # --- Status detection ---
    for status in TASK_STATUS_EN:
        if re.search(rf"\b{re.escape(status)}\b", lower):
            task["status"] = status
            task["is_task"] = True
    for status in TASK_STATUS_TH:
        if status in lower:
            task["status"] = status
            task["is_task"] = True

    # --- Assignee detection ---
    assignee_match = re.search(r"@(\w+)", text)
    if assignee_match:
        task["assignee"] = assignee_match.group(1)
        task["is_task"] = True
    assigned_match = re.search(r"(?:ให้|assigned to|delegate to)\s+@?(\w+)", lower)
    if assigned_match:
        task["assignee"] = assigned_match.group(1)
        task["is_task"] = True

    # --- Priority detection ---
    for p in TASK_PRIORITY:
        if p in lower:
            task["priority"] = p
            task["is_task"] = True

    # --- Explicit task markers ---
    if re.search(r"\b(task|todo|action item|follow up|to do)\b", lower):
        task["is_task"] = True
    thai_markers = ["ต้องทำ", "งานที่ต้อง", "action item", "follow up"]
    for marker in thai_markers:
        if f" {marker}" in lower or lower.startswith(marker):
            task["is_task"] = True

    return task if task["is_task"] else None


# ─── Guided Questions (pending_review confirmation flow) ───

GUIDED_ANSWER_YES = {"yes", "y", "ใช่", "ok", "okay", "ตกลง", "บันทึก", "save", "confirm", "ถูก", "ถูกต้อง"}
GUIDED_ANSWER_NO = {"no", "n", "ไม่", "cancel", "ยกเลิก", "ลบ", "delete", "skip", "ไม่ใช่", "ผิด"}
GUIDED_ANSWER_EDIT = {"edit", "แก้ไข", "เปลี่ยน", "change", "fix", "แก้"}


def _should_ask_guided_questions(doc: dict, line_tags: list[str]) -> bool:
    """Heuristics for when AI should ask the user before storing.

    Returns True when the AI is uncertain about classification.
    """
    # Very short text — could be a todo, could be noise
    content = doc.get("content", "")
    if len(content) < 50:
        return True

    # No tags from source — AI doesn't know how to classify
    if not doc.get("tags") and not line_tags:
        return True

    # Ambiguous doc_type (not clearly learning/note/task)
    doc_type = doc.get("doc_type", "")
    if doc_type in ("note", "learning") and len(content) < 200:
        return True

    return False


def _is_guided_answer(text: str) -> str | None:
    """Check if text is a reply to a pending review question.

    Returns 'yes', 'no', 'edit', or None if not a guided answer.
    """
    lower = text.lower().strip()
    for word in GUIDED_ANSWER_EDIT:
        if lower.startswith(word) or lower == word:
            return "edit"
    for word in GUIDED_ANSWER_YES:
        if lower == word or lower.startswith(f"{word} "):
            return "yes"
    for word in GUIDED_ANSWER_NO:
        if lower == word or lower.startswith(f"{word} "):
            return "no"
    return None


def _format_guided_question(doc: dict) -> tuple[str, list[dict]]:
    """Format a guided question message for LINE with Quick Reply buttons."""
    title = doc.get("title", "Unknown")
    content = doc.get("content", "")
    doc_type = doc.get("doc_type", "note")
    tags = doc.get("tags", [])
    concepts = doc.get("concepts", [])

    preview = content[:200] + ("..." if len(content) > 200 else "")
    tags_str = ", ".join(f"#{t}" for t in tags) if tags else "(ไม่มี)"
    concepts_str = ", ".join(concepts) if concepts else "(ไม่มี)"

    text = (
        f"ฉันไม่แน่ใจเกี่ยวกับข้อมูลนี้:\n\n"
        f"📝 {preview}\n\n"
        f"ประเภท: {doc_type}\n"
        f"Tags: {tags_str}\n"
        f"แนวคิด: {concepts_str}\n\n"
        f"บันทึกตามนี้มั้ย?"
    )

    quick_reply = [
        {"type": "action", "action": {"type": "message", "label": "✅ ใช่", "text": "ใช่"}},
        {"type": "action", "action": {"type": "message", "label": "❌ ไม่", "text": "ไม่"}},
        {"type": "action", "action": {"type": "message", "label": "✏️ แก้ไข", "text": "แก้ไข"}},
    ]

    return text, quick_reply


async def _handle_pending_review_reply(
    pg,
    access_token: str,
    reply_token: str,
    answer: str,
    user_id: str,
    text: str,
) -> dict:
    """Process a user's reply to a pending review question.

    Returns stats dict with what happened.
    """
    pending = await pg.get_pending_review_for_user(user_id)
    if not pending:
        # No pending review — treat as normal message
        return {"action": "none"}

    review_id = pending["id"]

    if answer == "yes":
        confirmed = await pg.confirm_pending_review(review_id)
        if confirmed.get("status") == "confirmed":
            # Push confirmed doc to store
            from src.ingest.push import Push
            from src.embed.ollama import OllamaEmbedder

            from src.config import Settings
            settings = Settings()
            try:
                embedder = OllamaEmbedder(settings)
            except Exception:
                embedder = None
            pusher = Push(pg, embedder)

            tags_list = confirmed.get("tags", [])
            if isinstance(tags_list, str):
                import json
                tags_list = json.loads(tags_list)
            concepts_list = confirmed.get("concepts", [])
            if isinstance(concepts_list, str):
                import json
                concepts_list = json.loads(concepts_list)

            result = await pusher.push_text(
                title=confirmed["title"],
                content=confirmed["content"],
                doc_type=confirmed.get("doc_type", "note"),
                scope=confirmed.get("scope", "shared"),
                source_type=confirmed.get("source_type", "line"),
                source_project=confirmed.get("source_project"),
                oracle_name=confirmed.get("oracle_name"),
                tags=tags_list,
                concepts=concepts_list,
            )

            # Apply tag rules
            from src.assistant.tag_rules import apply_tag_rules
            doc_id = result.get("doc_id", "")
            if doc_id and tags_list:
                await apply_tag_rules(pg, doc_id, tags_list, content=confirmed["content"])

            await _send_reply(access_token, reply_token, f"✅ บันทึกแล้ว: {confirmed['title']}")
            return {"action": "confirmed", "doc_id": doc_id}

    elif answer == "no":
        await pg.cancel_pending_review(review_id)
        await _send_reply(access_token, reply_token, "🗑 ยกเลิก — ไม่ได้บันทึกข้อมูลนี้")
        return {"action": "cancelled"}

    elif answer == "edit":
        # Parse edit instructions from user text
        updates = _parse_edit_instructions(text)
        if updates:
            # Update pending_review metadata with user's corrections
            # Re-prompt or store directly
            await pg.cancel_pending_review(review_id)
            await _send_reply(
                access_token, reply_token,
                f"✅ แก้ไขตามที่บอก: {updates}\nกำลังบันทึก...",
            )
            # Re-push with updated info
            return {"action": "edited", "updates": updates}

    return {"action": "unknown"}


def _parse_edit_instructions(text: str) -> dict:
    """Parse user edit instructions from text.

    Examples:
        "แก้ไข ประเภท:task Tags:งาน,ด่วน"
        "edit type:task tags:work"
    """
    import re
    updates = {}

    type_match = re.search(r"(?:ประเภท|type|doc_type)[:\s]*(\w+)", text, re.IGNORECASE)
    if type_match:
        updates["doc_type"] = type_match.group(1)

    tags_match = re.search(r"(?:tags?)[:\s]*([\w,ก-๙\s]+?)(?:$|\n|\.)", text, re.IGNORECASE)
    if tags_match:
        tags_str = tags_match.group(1).strip()
        updates["tags"] = [t.strip() for t in tags_str.split(",") if t.strip()]

    concepts_match = re.search(r"(?:concepts?|แนวคิด)[:\s]*([\w,ก-๙\s]+?)(?:$|\n|\.)", text, re.IGNORECASE)
    if concepts_match:
        concepts_str = concepts_match.group(1).strip()
        updates["concepts"] = [c.strip() for c in concepts_str.split(",") if c.strip()]

    return updates


async def _find_existing_task(pg, title: str, scope: str, tags: list[str] | None = None) -> dict | None:
    """Find an existing non-superseded task by title + tags."""
    try:
        tag_filter = tags[0] if tags else scope
        async with pg.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT kd.id, kd.content
                   FROM knowledge_documents kd
                   JOIN document_tags dt ON dt.doc_id = kd.id
                   JOIN tags t ON t.id = dt.tag_id
                   WHERE kd.title = $1 AND t.name = $2 AND kd.doc_type IN ('task', 'todo', 'reminder')
                     AND kd.superseded_by IS NULL
                   ORDER BY kd.created_at DESC LIMIT 1""",
                title, tag_filter,
            )
        if row:
            return {
                "id": str(row["id"]),
                "content": row["content"],
            }
    except Exception as e:
        log.warning("Failed to find existing task: %s", e)
    return None


# ─── LLM helpers via OpenRouter (with Ollama fallback) ────────────

async def _process_image_ocr(image_bytes: bytes, settings) -> str | None:
    """OCR image using OpenRouter vision (fallback to Ollama)."""
    from src.llm.openrouter_client import OpenRouterClient

    client = OpenRouterClient(settings)
    return await client.ocr_image(image_bytes)


async def _chat_with_user(text: str, settings, system_prompt: str | None = None) -> str:
    """Send text to OpenRouter chat (or Ollama fallback)."""
    from src.llm.openrouter_client import OpenRouterClient

    client = OpenRouterClient(settings)
    if not client.enabled:
        return "🤖 ขอโทษ ยังไม่สามารถคุยได้ในขณะนี้ (LLM ไม่พร้อม)"

    messages = [
        {"role": "system", "content": system_prompt or "คุณคือ Synapse Oracle ผู้ช่วยอัจฉริยะ พูดไทยได้ ตอบสั้น กระชับ ช่วยเหลือ"},
        {"role": "user", "content": text},
    ]
    try:
        return await client.chat(messages, temperature=0.7, max_tokens=500)
    except Exception as e:
        log.warning("Chat response failed: %s", e)
        return "🤖 ขอโทษ มีปัญหาในการตอบคำถาม กรุณาลองใหม่อีกครั้ง"


async def _hybrid_search(text: str, pg, settings, scope: str | None = None, limit: int = 10) -> list[dict]:
    """Run hybrid search (vector + FTS) with fallback to FTS-only."""
    from src.embed.ollama import OllamaEmbedder
    from src.retrieve.hybrid_search import HybridSearch

    try:
        embedder = OllamaEmbedder(settings)
        searcher = HybridSearch(pg, embedder=embedder)
        return await searcher.search(text, scope=scope, limit=limit)
    except Exception as e:
        log.warning("Hybrid search failed, falling back to FTS: %s", e)
        try:
            return await pg.search_fts(text, scope=scope, limit=limit)
        except Exception as e2:
            log.warning("FTS search also failed: %s", e2)
            return []


async def _answer_question(
    text: str,
    pg,
    settings,
    scope: str | None = None,
    limit: int = 5,
) -> str:
    """Search knowledge base and generate an answer via LLM."""
    from src.llm.openrouter_client import OpenRouterClient

    try:
        # Hybrid search: vector (semantic) + FTS (keyword) via RRF fusion
        results = await _hybrid_search(text, pg, settings, scope=None, limit=limit)
    except Exception as e:
        log.warning("Search failed: %s", e)
        results = []

    if not results:
        return "🤖 ไม่พบข้อมูลที่เกี่ยวข้องในฐานความรู้ ลองถามใหม่หรือเพิ่มข้อมูลก่อนนะครับ"

    context_parts = [_format_source_context(i, doc) for i, doc in enumerate(results, 1)]
    context = "\n\n".join(context_parts)

    client = OpenRouterClient(settings)
    if not client.enabled:
        lines = [_format_source_line(i, r) for i, r in enumerate(results, 1)]
        return "🔍 ผลการค้นหา:\n" + "\n".join(lines)

    system = (
        "You are Synapse Oracle, a helpful knowledge assistant. "
        "Answer the user's question using ONLY the provided context documents. "
        "If the context doesn't contain the answer, say so honestly. "
        "Respond in Thai if the user asked in Thai, otherwise English. "
        "Be concise. "
        "IMPORTANT: Do NOT use markdown formatting (no **bold**, no ## headers, "
        "no - bullet lists, no > quotes, no `code` marks). "
        "Use plain text only with emoji and Unicode characters for emphasis. "
        "Use • for bullet points, use numbers for lists."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {text}\n\nAnswer:"},
    ]
    try:
        answer = await client.chat(messages, temperature=0.3, max_tokens=800)
        answer = _strip_markdown(answer)
        source_lines = [_format_source_line(i, r) for i, r in enumerate(results, 1)]
        return f"{answer}\n\n📚 ที่มา:\n" + "\n".join(source_lines)
    except Exception as e:
        log.warning("Q&A generation failed: %s", e)
        lines = [_format_source_line(i, r) for i, r in enumerate(results, 1)]
        return "🔍 ผลการค้นหา:\n" + "\n".join(lines)


# ─── Command handlers ────────────────────────────────────────────

async def _handle_task_command(cmd: str, args: str, pg, settings, scope: str | None = None, line_tags: list | None = None, access_token: str = "", reply_token: str = "") -> dict | None:
    """Handle /task, /todo, /remind commands — explicitly create a task document.

    These commands bypass the intent check in _extract_task_info because
    the user's intent to create a task is explicit (they typed /task).

    Returns stats dict: {created, superseded} or None on error.
    """
    if not args or not args.strip():
        msg = "📝 ใช้: /task <ข้อความงาน>\n" \
              "ตัวอย่าง:\n" \
              "  /task ส่งรายงานภายในวันศุกร์\n" \
              "  /todo deploy app due tomorrow @john\n" \
              "  /remind โทรคุยกับทีม วันจันทร์หน้า"
        if access_token and reply_token:
            await _send_reply(access_token, reply_token, msg)
        return None

    text = args.strip()

    # Extract task info with aggressive detection (require_intent=False)
    task_info = _extract_task_info(text, require_intent=False)
    if not task_info:
        # Even without detected dates, if user typed /task, it IS a task
        task_info = {"is_task": True, "due_date": None, "status": "pending", "assignee": None, "priority": "medium"}

    title = text[:200] if len(text) > 200 else text

    # Build tags from command type + line context
    cmd_tag_map = {"task": "task", "todo": "task", "remind": "reminder"}
    task_tag = cmd_tag_map.get(cmd, "task")
    tags = list(line_tags) if line_tags else []
    if task_tag not in tags:
        tags.append(task_tag)

    # Determine doc_type from command
    if cmd == "remind":
        doc_type = "reminder"
    else:
        doc_type = "todo"

    metadata = {
        "source": "line_command",
        "task": {
            "due_date": task_info.get("due_date"),
            "status": task_info.get("status") or "pending",
            "assignee": task_info.get("assignee"),
            "priority": task_info.get("priority") or "medium",
        },
    }
    if task_info.get("due_date"):
        metadata["task"]["due_date"] = task_info["due_date"]

    concepts = ["line", "line_text", f"line_command_{cmd}", task_tag]

    # Find existing task to supersede (by title + first tag)
    existing = await _find_existing_task(pg, title, scope, tags=tags)
    if existing:
        from src.ingest.push import Push
        from src.embed.ollama import OllamaEmbedder
        embedder = None
        try:
            embedder = OllamaEmbedder(settings)
        except Exception:
            pass
        pusher = Push(pg, embedder)
        try:
            result = await pusher.push_text(
                title=title,
                content=text,
                doc_type=doc_type,
                source_type=f"line_command_{cmd}",
                source_project="line-integration",
                oracle_name="line-bot",
                tags=tags,
                concepts=concepts,
                metadata=metadata,
            )
            # Also supersede old task
            try:
                await pg.supersede(existing["id"], text, reason=f"task_update_via_{cmd}", new_title=title)
                if access_token and reply_token:
                    due_str = f" (due: {task_info['due_date']})" if task_info.get('due_date') else ""
                    await _send_reply(access_token, reply_token, f"📝 Task updated{due_str}")
                return {"created": 1, "superseded": 1}
            except Exception as e:
                log.warning("Task supersede failed: %s", e)
        except Exception as e:
            log.warning("Task push failed: %s", e)
            if access_token and reply_token:
                await _send_reply(access_token, reply_token, f"❌ สร้าง task ไม่สำเร็จ: {e}")
            return None

    # New task
    from src.ingest.push import Push
    from src.embed.ollama import OllamaEmbedder
    embedder = None
    try:
        embedder = OllamaEmbedder(settings)
    except Exception:
        pass
    pusher = Push(pg, embedder)

    try:
        result = await pusher.push_text(
            title=title,
            content=text,
            doc_type=doc_type,
            source_type=f"line_command_{cmd}",
            source_project="line-integration",
            oracle_name="line-bot",
            tags=tags,
            concepts=concepts,
            metadata=metadata,
        )
        # Apply tag rules for scheduling
        doc_id = result.get("id", "")
        if doc_id:
            try:
                from src.assistant.tag_rules import apply_tag_rules
                await apply_tag_rules(pg, doc_id, tags, content=text)
            except Exception as e:
                log.warning("Tag rules failed for /task: %s", e)

        due_str = f" (due: {task_info['due_date']})" if task_info.get('due_date') else ""
        if access_token and reply_token:
            await _send_reply(access_token, reply_token, f"✅ สร้าง {cmd} แล้ว{due_str}")
        return {"created": 1, "superseded": 0}
    except Exception as e:
        log.warning("Task push failed: %s", e)
        if access_token and reply_token:
            await _send_reply(access_token, reply_token, f"❌ สร้าง task ไม่สำเร็จ: {e}")
        return None



async def _handle_command(
    cmd: str,
    args: str,
    pg,
    settings,
    scope: str | None = None,
) -> str:
    """Handle bot commands and return reply text."""

    if cmd == "search":
        if not args:
            return "🔍 ใช้: /search <คำค้นหา>"
        try:
            # Hybrid search: vector (semantic) + FTS (keyword) via RRF fusion
            results = await _hybrid_search(args, pg, settings, scope=None, limit=5)
        except Exception as e:
            log.warning("Command search failed: %s", e)
            return "❌ ค้นหาล้มเหลว"
        if not results:
            return "🔍 ไม่พบผลลัพธ์"
        lines = [_format_source_line(i, doc) for i, doc in enumerate(results, 1)]
        return "🔍 ผลการค้นหา:\n" + "\n".join(lines)

    if cmd == "recent":
        target_scope = args.strip() or scope or None
        try:
            docs = await pg.list_docs(scope=target_scope, limit=5)
        except Exception as e:
            log.warning("Command recent failed: %s", e)
            return "❌ ดึงข้อมูลล่าสุดล้มเหลว"
        if not docs:
            return "📭 ไม่มีเอกสารล่าสุด"
        lines = []
        for i, doc in enumerate(docs, 1):
            title = doc.get("title", "Untitled")
            lines.append(f"{i}. {title}")
        header = f"📄 เอกสารล่าสุด ({target_scope or 'ทั้งหมด'}):\n"
        return header + "\n".join(lines)

    if cmd == "stats":
        try:
            data = await pg.stats()
        except Exception as e:
            log.warning("Command stats failed: %s", e)
            return "❌ ดึงสถิติล้มเหลว"
        total = data.get("total_documents", 0)
        scopes = data.get("total_scopes", 0)
        return (
            f"📊 สถิติ Synapse:\n"
            f"  เอกสารทั้งหมด: {total}\n"
            f"  Tags ทั้งหมด: {scopes}"
        )

    if cmd == "scopes" or cmd == "tags":
        try:
            tag_list = await pg.list_tags()
        except Exception as e:
            log.warning("Command tags failed: %s", e)
            return "❌ ดึงรายการ tag ล้มเหลว"
        if not tag_list:
            return "📭 ไม่มี tag"
        lines = [f"• {t.get('name', '')} ({t.get('doc_count', 0)})" for t in tag_list]
        return "🏷️ Tags:\n" + "\n".join(lines)

    if cmd == "ask":
        if not args:
            return "❓ ใช้: /ask <คำถาม>"
        from src.llm.openrouter_client import OpenRouterClient
        try:
            # Hybrid search: vector (semantic) + FTS (keyword) via RRF fusion
            results = await _hybrid_search(args, pg, settings, scope=None, limit=10)
        except Exception as e:
            log.warning("Ask search failed: %s", e)
            return "❌ ค้นหาล้มเหลว"
        if not results:
            return "🤖 ไม่พบข้อมูลที่เกี่ยวข้องในฐานความรู้"
        context_parts = [_format_source_context(i, doc) for i, doc in enumerate(results, 1)]
        context = "\n\n".join(context_parts)
        client = OpenRouterClient(settings)
        if not client.enabled:
            lines = [_format_source_line(i, r) for i, r in enumerate(results, 1)]
            return "🔍 ผลการค้นหา:\n" + "\n".join(lines)
        system = (
            "You are Synapse Oracle, a knowledgeable assistant that provides thoughtful, "
            "analytical answers in Thai (or English if the user asks in English).\n\n"
            "Guidelines:\n"
            "- First, understand what the user REALLY wants to know — analyze their intent.\n"
            "- Answer using ONLY the provided context documents.\n"
            "- Structure your answer: give the main answer first, then supporting details.\n"
            "- If the context is rich with detail, provide a thorough response — don't truncate.\n"
            "- If the context doesn't contain the answer, say so honestly.\n"
            "- Cite which document [N] each key point comes from.\n\n"
            "IMPORTANT: Do NOT use markdown formatting. This message appears in LINE messenger "
            "which does NOT render markdown. No **bold**, no ## headers, no - bullet lists, "
            "no > blockquotes, no `code` marks. Use plain text only:\n"
            "- Use emoji and Unicode characters for emphasis (📌 💡 ✅ ❌ etc.)\n"
            "- Use • for bullet points\n"
            "- Use numbers for lists\n"
            "- Use plain text with line breaks for structure"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {args}\n\nProvide a thorough, analytical answer:"},
        ]
        try:
            answer = await client.chat(messages, temperature=0.7, max_tokens=1500)
            answer = _strip_markdown(answer)
            source_lines = [_format_source_line(i, r) for i, r in enumerate(results, 1)]
            return f"{answer}\n\n📚 ที่มา:\n" + "\n".join(source_lines)
        except Exception as e:
            log.warning("Ask LLM failed: %s", e)
            lines = [_format_source_line(i, r) for i, r in enumerate(results, 1)]
            return "🔍 ผลการค้นหา:\n" + "\n".join(lines)

    if cmd in ("task", "todo", "remind"):
        # These are handled in process_line_events, not here,
        # because they need pg, settings, access_token, reply_token
        # Return None to signal caller to handle them
        return None

    if cmd == "help":
        return (
            "🤖 Synapse Oracle Assistant\n\n"
            "คำสั่ง:\n"
            "  /search <คำค้นหา> — ค้นหาความรู้\n"
            "  /ask <คำถาม> — ถามและตอบจากความรู้\n"
            "  /recent [scope] — เอกสารล่าสุด\n"
            "  /stats — สถิติฐานความรู้\n"
            "  /tags — รายการ tags\n"
            "  /task <ข้อความ> — สร้าง task\n"
            "  /todo <ข้อความ> — สร้าง todo\n"
            "  /remind <ข้อความ> — สร้าง reminder\n"
            "  /help — ช่วยเหลือ\n\n"
            "ส่งข้อความปกติ → บันทึกเป็นความรู้โดยอัตโนมัติ\n"
            "ถามคำถามชัดเจน → ใช้ /ask เพื่อค้นหาและตอบ"
        )

    return "❓ ไม่รู้จักคำสั่ง"


# ─── Media helpers ──────────────────────────────────────────────

async def _download_line_media(message_id: str, access_token: str) -> bytes:
    """Download media content from LINE Messaging API."""
    import httpx

    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content


def event_to_scope(event: dict) -> str:
    """Determine synapse scope from LINE event source (deprecated — use event_to_tags)."""
    return event_to_tags(event)[0] if event_to_tags(event) else "line-unknown"


def event_to_tags(event: dict) -> list[str]:
    """Determine synapse tags from LINE event source."""
    source = event.get("source", {})
    source_type = source.get("type", "user")
    tags = ["line", source_type]
    if source_type == "group":
        tags.append(f"line-group-{source.get('groupId', 'unknown')[:16]}")
    elif source_type == "room":
        tags.append(f"line-room-{source.get('roomId', 'unknown')[:16]}")
    else:
        tags.append(f"line-user-{source.get('userId', 'unknown')[:16]}")
    return tags


def _chat_id_from_event(event: dict) -> str:
    """Get a chat identifier for scope/grouping."""
    source = event.get("source", {})
    if source.get("type") == "group":
        return source.get("groupId", "")
    if source.get("type") == "room":
        return source.get("roomId", "")
    return source.get("userId", "")


def _is_group_chat(event: dict) -> bool:
    """Return True if event is from a group or room chat."""
    source_type = event.get("source", {}).get("type", "")
    return source_type in ("group", "room")


async def _resolve_source_name(access_token: str, source: dict) -> str:
    """Resolve a LINE source to a human-readable display name.

    User → GET /profile/{userId} → displayName
    Group → GET /group/{groupId}/summary → groupName
    Room → skipped (no LINE API for room name), falls back to user profile
    """
    import httpx

    source_type = source.get("type", "user")
    user_id = source.get("userId", "")
    base = "https://api.line.me/v2/bot"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            if source_type == "group":
                group_id = source.get("groupId", "")
                if group_id:
                    resp = await client.get(f"{base}/group/{group_id}/summary", headers=headers)
                    if resp.status_code == 200:
                        name = resp.json().get("groupName", "")
                        if name:
                            log.info("_resolve_source_name: group name resolved -> %r", name)
                            return name
            # user / room: resolve sender profile
            if user_id:
                resp = await client.get(f"{base}/profile/{user_id}", headers=headers)
                if resp.status_code == 200:
                    name = resp.json().get("displayName", "")
                    if name:
                        log.info("_resolve_source_name: profile name resolved -> %r", name)
                        return name
    except Exception:
        log.warning("Failed to resolve source name for %s/%s", source_type, user_id)

    # Fallback: return a shortened readable ID
    raw_id = source.get("groupId") or user_id or "unknown"
    result = f"{source_type}:{raw_id[:12]}"
    log.info("_resolve_source_name: type=%s result=%r", source_type, result)
    return result


# ─── Knowledge document builder (no pending review) ─────────────

async def _build_knowledge_doc(
    event: dict,
    settings,
    source_name: str = "",
) -> dict | None:
    """Build a knowledge document dict from a LINE event.

    Returns dict or None if should be skipped (sticker, too short, etc.).
    source_name: human-readable display name for the source user/group/room.
    """
    message = event.get("message", {})
    msg_type = message.get("type", "")
    source = event.get("source", {})
    user_id = source.get("userId", "")
    chat_id = _chat_id_from_event(event)
    reply_token = event.get("replyToken", "")
    timestamp = event.get("timestamp", 0)
    message_id = message.get("id", "")

    if msg_type == "sticker":
        return None

    if event.get("type") != "message":
        return None

    scope = event_to_scope(event)
    source_type = source.get("type", "user")
    line_tags = event_to_tags(event)

    content = ""
    title = "LINE Message"
    media_size = 0

    if msg_type == "text":
        content = message.get("text", "")
        if len(content) < 10:
            log.info("_build_knowledge_doc: skipping short text (%d chars): %r", len(content), content)
            return None
        title = "LINE Text"

    elif msg_type == "location":
        addr = message.get("address", "")
        lat = message.get("latitude", 0)
        lng = message.get("longitude", 0)
        content = f"📍 {addr}\nพิกัด: {lat}, {lng}"
        title = "LINE Location"

    elif msg_type == "image":
        channel_token = getattr(settings, "line_channel_access_token", "")
        if channel_token and message_id:
            try:
                image_bytes = await _download_line_media(message_id, channel_token)
                ocr_text = await _process_image_ocr(image_bytes, settings)
                if ocr_text:
                    content = ocr_text
                    title = "LINE Image (OCR)"
                else:
                    content = "[image: OCR returned no text]"
                    title = "LINE Image (no text)"
            except Exception as e:
                log.warning("Image OCR failed: %s", e)
                content = "[image: OCR failed]"
                title = "LINE Image (OCR failed)"
        else:
            content = "[image: no access token for download]"
            title = "LINE Image"

    elif msg_type == "video":
        channel_token = getattr(settings, "line_channel_access_token", "")
        if channel_token and message_id:
            try:
                video_bytes = await _download_line_media(message_id, channel_token)
                media_size = len(video_bytes)
                content = f"[video: {media_size} bytes]"
                title = "LINE Video (รอ transcript)"
            except Exception as e:
                log.warning("Video download failed: %s", e)
                content = "[video: download failed]"
                title = "LINE Video"
        else:
            content = "[video: no access token for download]"
            title = "LINE Video"

    elif msg_type == "audio":
        channel_token = getattr(settings, "line_channel_access_token", "")
        if channel_token and message_id:
            try:
                audio_bytes = await _download_line_media(message_id, channel_token)
                media_size = len(audio_bytes)
                content = f"[audio: {media_size} bytes]"
                title = "LINE Audio (รอ transcript)"
            except Exception as e:
                log.warning("Audio download failed: %s", e)
                content = "[audio: download failed]"
                title = "LINE Audio"
        else:
            content = "[audio: no access token for download]"
            title = "LINE Audio"

    elif msg_type == "file":
        content = f"[file: {message.get('fileName', 'unknown')}]"
        title = "LINE File"

    else:
        content = f"[{msg_type}]"
        title = f"LINE {msg_type.capitalize()}"

    # --- Knowledge mode: regular messages are always "note" ---
    # Task creation requires explicit /task, /todo, or /remind command.
    # Auto-detection was too aggressive: dates, @mentions, and casual words
    # were incorrectly triggering task classification.
    doc_type = "note"
    task_info = None
    concepts = ["line", f"line_{msg_type}", f"line_{source_type}"]
    doc_tags = list(line_tags)  # copy the event tags
    doc_tags.append(msg_type)
    # Replace raw-ID tags with readable source name
    if source_name:
        doc_tags = [t for t in doc_tags if not t.startswith("line-user-")
                    and not t.startswith("line-group-")
                    and not t.startswith("line-room-")]
        doc_tags.insert(0, source_name)
    log.info("_build_knowledge_doc: source_name=%r doc_tags=%s", source_name, doc_tags)
    # task_info is always None for regular messages (tasks via /task command only)

    metadata = {
        "source": {
            "platform": "line",
            "type": source_type,
            "id": source.get("groupId") or source.get("roomId") or user_id or "",
            "user_id": user_id,
            "name": source_name or source_type,
        },
        "message_id": message_id,
        "message_type": msg_type,
        "reply_token": reply_token,
        "timestamp": timestamp,
    }

    # Mark video/audio as needing transcription
    if msg_type in ("video", "audio"):
        metadata["needs_transcription"] = True
        metadata["media_size"] = media_size

    # task metadata removed — tasks now created via /task command only

    line_source = f"line-{source_type}"
    return {
        "title": title,
        "content": content,
        "scope": scope,
        "doc_type": doc_type,
        "source_type": line_source,
        "source_project": "line-integration",
        "oracle_name": "line-bot",
        "tags": doc_tags,
        "concepts": concepts,
        "metadata": {**metadata, "source_type": line_source},
        "reply_token": reply_token,
        "user_id": user_id,
        "chat_id": chat_id,
    }


# ─── Main event processor ──────────────────────────────────────

async def process_line_events(
    events: list[dict],
    pg,
    access_token: str = "",
    settings = None,
) -> dict:
    """Process LINE events: auto-ingest pipeline.

    All messages → convert to text → push to synapse.
    Commands → handled interactively.
    Stickers + short text → skipped.

    Returns stats dict.
    """
    answered = 0
    commands = 0
    created = 0
    pushed = 0
    replied = 0
    skipped = 0
    superseded = 0
    deduplicated = 0

    # Lazy-init Push pipeline (one per batch)
    pusher = None

    for event in events:
        if event.get("type") != "message":
            continue

        message = event.get("message", {})
        msg_type = message.get("type", "")
        source = event.get("source", {})
        reply_token = event.get("replyToken", "")
        scope = event_to_scope(event)
        line_tags = event_to_tags(event)
        silent = _is_group_chat(event)

        # 1. Text commands & Q&A (all chat types)
        if msg_type == "text":
            text = message.get("text", "")

            # 1A. Commands (work in DM, group, and room)
            cmd_result = _is_command(text)
            if cmd_result:
                cmd, args = cmd_result

                # Task commands need pg, settings, access_token, etc.
                if cmd in ("task", "todo", "remind"):
                    task_result = await _handle_task_command(
                        cmd, args, pg, settings, scope=scope,
                        line_tags=line_tags, access_token=access_token,
                        reply_token=reply_token,
                    )
                    commands += 1
                    if task_result:
                        if task_result.get("superseded"):
                            superseded += 1
                        if task_result.get("created"):
                            created += 1
                        if access_token and reply_token:
                            replied += 1
                    continue

                reply = await _handle_command(cmd, args, pg, settings, scope=scope)
                if access_token and reply_token:
                    await _send_reply(access_token, reply_token, reply)
                    replied += 1
                commands += 1
                continue

            # 1B. Guided answer reply — user responding to pending review question
            if not _is_group_chat(event):
                guided_answer = _is_guided_answer(text)
                if guided_answer:
                    user_id = source.get("userId", "")
                    result = await _handle_pending_review_reply(
                        pg, access_token, reply_token, guided_answer, user_id, text,
                    )
                    if result.get("action") != "none":
                        replied += 1
                        if result.get("action") == "confirmed":
                            created += 1
                        continue

        # 2. Skip stickers
        if msg_type == "sticker":
            skipped += 1
            continue

        # 3. Resolve source name for display
        source_name = ""
        if access_token:
            source_name = await _resolve_source_name(access_token, source)
            log.info("process_line_events: resolved source_name=%r", source_name)
        else:
            log.info("process_line_events: no access_token, skipping source name resolution")

        # 4. Build knowledge document
        doc = await _build_knowledge_doc(event, settings, source_name=source_name)
        if doc is None:
            skipped += 1
            continue

        # 4.5 Guided Questions — ask user if AI is unsure (DM only, not groups)
        if not silent and _should_ask_guided_questions(doc, line_tags):
            if access_token and reply_token:
                # Save to pending_review
                await pg.create_pending_review({
                    "title": doc["title"],
                    "content": doc["content"],
                    "summary": doc.get("summary"),
                    "scope": scope,
                    "doc_type": doc["doc_type"],
                    "source_type": doc["source_type"],
                    "source_project": doc.get("source_project"),
                    "oracle_name": doc.get("oracle_name"),
                    "tags": doc["tags"],
                    "concepts": doc["concepts"],
                    "metadata": doc.get("metadata", {}),
                    "reply_token": reply_token,
                    "user_id": source.get("userId", ""),
                    "chat_id": source.get("userId", ""),
                })
                question, quick_reply = _format_guided_question(doc)
                await _send_reply(access_token, reply_token, question, quick_reply)
                replied += 1
            else:
                # No LINE reply capability — fall through to auto-push
                # instead of skipping (can't ask user, so store directly)
                log.info("process_line_events: no access_token, skipping guided questions, storing directly")
            # Don't continue — fall through to auto-push

        # 5. Task supersede check — only for explicitly-created tasks via /task /todo /remind
        # Regular messages are always doc_type="note" now, so this block
        # is a safety net. Task supersede is handled in _handle_task_command.
        if doc["doc_type"] in ("task", "todo", "reminder"):
            existing = await _find_existing_task(pg, doc["title"], scope, tags=line_tags)
            if existing:
                try:
                    await pg.supersede(
                        existing["id"],
                        doc["content"],
                        reason="task_update",
                        new_title=doc["title"],
                    )
                    superseded += 1
                    if access_token and reply_token and not silent:
                        await _send_reply(access_token, reply_token, "📝 Task updated")
                        replied += 1
                    continue
                except Exception as e:
                    log.warning("Task supersede failed: %s", e)

        # 5. Auto-push via Push pipeline
        if pusher is None:
            from src.ingest.push import Push
            from src.embed.ollama import OllamaEmbedder

            embedder = None
            try:
                embedder = OllamaEmbedder(settings)
            except Exception:
                pass
            pusher = Push(pg, embedder)

        try:
            result = await pusher.push_text(
                title=doc["title"],
                content=doc["content"],
                doc_type=doc["doc_type"],
                source_type=doc["source_type"],
                source_project=doc["source_project"],
                oracle_name=doc["oracle_name"],
                tags=doc["tags"],
                concepts=doc["concepts"],
                skip_semantic_dedup=not silent,  # DM: bypass semantic dedup
            )
            status = result.get("status", "")
            if status == "duplicate":
                deduplicated += 1
            elif status == "semantic_duplicate":
                deduplicated += 1
            elif status == "indexed":
                pushed += 1
                created += 1
                # Apply tag rules (task scheduling, alerts)
                doc_id = result.get("id", "")
                if doc_id and doc.get("tags"):
                    try:
                        from src.assistant.tag_rules import apply_tag_rules
                        actions = await apply_tag_rules(pg, doc_id, doc["tags"], content=doc["content"])
                        log.info("Tag rules applied: %s", actions)
                    except Exception as e:
                        log.warning("Tag rule application failed: %s", e)
            else:
                created += 1

            # Reply confirmation (DM only, not in groups)
            if access_token and reply_token and not silent:
                if status in ("duplicate", "semantic_duplicate"):
                    await _send_reply(access_token, reply_token, "📝 ข้อมูลคล้ายกันอยู่แล้ว — ข้าม")
                elif status == "indexed":
                    await _send_reply(access_token, reply_token, "✅ บันทึกความรู้แล้ว")
                else:
                    await _send_reply(access_token, reply_token, "✅ บันทึกความรู้แล้ว")
                replied += 1

        except Exception as e:
            log.warning("Auto-push failed: %s", e)
            skipped += 1
            if access_token and reply_token and not silent:
                await _send_reply(access_token, reply_token, f"❌ บันทึกไม่สำเร็จ: {e}")
                replied += 1

    return {
        "answered": answered,
        "commands": commands,
        "created": created,
        "pushed": pushed,
        "replied": replied,
        "skipped": skipped,
        "superseded": superseded,
        "deduplicated": deduplicated,
    }


async def _send_reply(
    access_token: str,
    reply_token: str,
    text: str,
    quick_reply: list[dict] | None = None,
) -> None:
    """Send a reply message via LINE Messaging API. Errors are logged, never raised."""
    import httpx

    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    msg: dict = {"type": "text", "text": text}
    if quick_reply:
        msg["quickReply"] = {"items": quick_reply}

    payload = {
        "replyToken": reply_token,
        "messages": [msg],
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            log.debug("LINE reply sent: %s", resp.status_code)
    except Exception as e:
        log.warning("LINE reply failed (non-fatal): %s", e)
