"""LINE webhook handler — full chatbot: capture, Q&A, commands, and chat.

Group/room mode: SILENT — auto-capture without confirmation.
Task detection: parses due date, status, assignee, priority.
Task dedup: supersede existing task with same title + scope.
"""

import base64
import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, Request

log = logging.getLogger("synapse.line")

# ─── Confirmation keywords (Thai + English) ──────────────────────
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
COMMANDS = {"search", "recent", "stats", "scopes", "help", "ask"}

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


def _is_confirmation_reply(text: str) -> tuple[str, str] | None:
    """Check if text is a confirmation reply. Returns (action, clean_text) or None."""
    lower = text.strip().lower()
    if lower in CONFIRM_YES:
        return ("confirm", "")
    if lower in CONFIRM_NO:
        return ("cancel", "")
    if lower in CONFIRM_EDIT:
        return ("edit", "")
    for prefix in ("yes ", "ใช่ ", "ok ", "confirm "):
        if lower.startswith(prefix):
            return ("confirm", text[len(prefix):].strip())
    for prefix in ("no ", "ไม่ ", "cancel "):
        if lower.startswith(prefix):
            return ("cancel", text[len(prefix):].strip())
    for prefix in ("edit ", "แก้ไข "):
        if lower.startswith(prefix):
            return ("edit", text[len(prefix):].strip())
    return None


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
    """Detect whether text is clearly a question.

    Default flow is knowledge capture; questions must be explicit.
    """
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


def _extract_task_info(text: str) -> dict | None:
    """Parse task metadata from text. Returns dict or None if not a task."""
    lower = text.lower()
    task = {"is_task": False, "due_date": None, "status": None, "assignee": None, "priority": None}

    # --- Due date detection ---
    # Thai Buddhist year (e.g. 25/5/2567 or 25-05-67)
    thai_date_match = re.search(
        r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\s*(?:พ\.ศ\.?|ค\.ศ\.?)?",
        text,
    )
    if thai_date_match:
        day, month, year = thai_date_match.groups()
        if year:
            year_int = int(year)
            if year_int > 2500:
                year_int -= 543  # Buddhist to Gregorian
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
    # @username pattern
    assignee_match = re.search(r"@(\w+)", text)
    if assignee_match:
        task["assignee"] = assignee_match.group(1)
        task["is_task"] = True
    # "ให้ @user" or "assigned to"
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
    # English: word boundaries work
    if re.search(r"\b(task|todo|action item|follow up|to do)\b", lower):
        task["is_task"] = True
    # Thai: check for standalone phrases (space-separated or sentence edges)
    thai_markers = ["ต้องทำ", "งานที่ต้อง", "action item", "follow up"]
    for marker in thai_markers:
        if f" {marker}" in lower or lower.startswith(marker):
            task["is_task"] = True

    return task if task["is_task"] else None


async def _find_existing_task(pg, title: str, scope: str) -> dict | None:
    """Find an existing non-superseded task by title + scope."""
    try:
        async with pg.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, content, metadata, status as doc_status
                   FROM knowledge_documents
                   WHERE title = $1 AND scope = $2 AND doc_type = 'task'
                     AND superseded_by IS NULL
                   ORDER BY created_at DESC LIMIT 1""",
                title, scope,
            )
        if row:
            return {
                "id": str(row["id"]),
                "content": row["content"],
                "metadata": row["metadata"] or {},
            }
    except Exception as e:
        log.warning("Failed to find existing task: %s", e)
    return None


# ─── LLM helpers via OpenRouter (with Ollama fallback) ────────────

def _to_bullets(text: str) -> str:
    """Convert text into bullet-point format."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ""
    bullets = []
    for line in lines:
        if line.startswith(("-", "•", "*", "1.", "2.", "3.")):
            bullets.append(line)
        else:
            # Split by sentences if no bullets found
            sentences = [s.strip() for s in line.split(".") if s.strip()]
            for s in sentences:
                bullets.append(f"• {s}")
    return "\n".join(bullets)


async def _summarize_text(text: str, settings) -> str:
    """Summarize text using OpenRouter (fallback to Ollama)."""
    from src.llm.openrouter_client import OpenRouterClient

    client = OpenRouterClient(settings)
    try:
        return await client.summarize(text, language="auto")
    except Exception as e:
        log.warning("Summarization failed: %s", e)
        return text[:200]


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
        results = await pg.search_fts(text, scope=scope, limit=limit)
    except Exception as e:
        log.warning("Search failed: %s", e)
        results = []

    if not results:
        return "🤖 ไม่พบข้อมูลที่เกี่ยวข้องในฐานความรู้ ลองถามใหม่หรือเพิ่มข้อมูลก่อนนะครับ"

    context_parts = []
    for i, doc in enumerate(results, 1):
        snippet = doc.get("content", "")[:300]
        title = doc.get("title", "Untitled")
        context_parts.append(f"[{i}] {title}:\n{snippet}")
    context = "\n\n".join(context_parts)

    client = OpenRouterClient(settings)
    if not client.enabled:
        lines = [f"{i+1}. {r.get('title', '')}" for i, r in enumerate(results)]
        return "🔍 ผลการค้นหา:\n" + "\n".join(lines)

    system = (
        "You are Synapse Oracle, a helpful knowledge assistant. "
        "Answer the user's question using ONLY the provided context documents. "
        "If the context doesn't contain the answer, say so honestly. "
        "Respond in Thai if the user asked in Thai, otherwise English. "
        "Be concise."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {text}\n\nAnswer:"},
    ]
    try:
        answer = await client.chat(messages, temperature=0.3, max_tokens=800)
        sources = "\n".join(
            f"  {i+1}. {r.get('title', '')}" for i, r in enumerate(results)
        )
        return f"{answer}\n\n📚 ที่มา:\n{sources}"
    except Exception as e:
        log.warning("Q&A generation failed: %s", e)
        lines = [f"{i+1}. {r.get('title', '')}" for i, r in enumerate(results)]
        return "🔍 ผลการค้นหา:\n" + "\n".join(lines)


# ─── Command handlers ────────────────────────────────────────────

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
            results = await pg.search_fts(args, scope=scope, limit=5)
        except Exception as e:
            log.warning("Command search failed: %s", e)
            return "❌ ค้นหาล้มเหลว"
        if not results:
            return "🔍 ไม่พบผลลัพธ์"
        lines = []
        for i, doc in enumerate(results, 1):
            title = doc.get("title", "Untitled")
            lines.append(f"{i}. {title}")
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
            f"  Scope ทั้งหมด: {scopes}"
        )

    if cmd == "scopes":
        try:
            scopes = await pg.list_scopes()
        except Exception as e:
            log.warning("Command scopes failed: %s", e)
            return "❌ ดึงรายการ scope ล้มเหลว"
        if not scopes:
            return "📭 ไม่มี scope"
        lines = [f"• {s.get('name', '')}" for s in scopes]
        return "🗂️ Scopes:\n" + "\n".join(lines)

    if cmd == "ask":
        if not args:
            return "❓ ใช้: /ask <คำถาม>"
        # Trigger Q&A directly via command
        from src.llm.openrouter_client import OpenRouterClient
        try:
            results = await pg.search_fts(args, scope=scope, limit=5)
        except Exception as e:
            log.warning("Ask search failed: %s", e)
            return "❌ ค้นหาล้มเหลว"
        if not results:
            return "🤖 ไม่พบข้อมูลที่เกี่ยวข้องในฐานความรู้"
        context_parts = []
        for i, doc in enumerate(results, 1):
            snippet = doc.get("content", "")[:300]
            title = doc.get("title", "Untitled")
            context_parts.append(f"[{i}] {title}:\n{snippet}")
        context = "\n\n".join(context_parts)
        client = OpenRouterClient(settings)
        if not client.enabled:
            lines = [f"{i+1}. {r.get('title', '')}" for i, r in enumerate(results)]
            return "🔍 ผลการค้นหา:\n" + "\n".join(lines)
        system = (
            "You are Synapse Oracle, a helpful knowledge assistant. "
            "Answer the user's question using ONLY the provided context documents. "
            "If the context doesn't contain the answer, say so honestly. "
            "Respond in Thai if the user asked in Thai, otherwise English. "
            "Be concise."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {args}\n\nAnswer:"},
        ]
        try:
            answer = await client.chat(messages, temperature=0.3, max_tokens=800)
            sources = "\n".join(f"  {i+1}. {r.get('title', '')}" for i, r in enumerate(results))
            return f"{answer}\n\n📚 ที่มา:\n{sources}"
        except Exception as e:
            log.warning("Ask LLM failed: %s", e)
            lines = [f"{i+1}. {r.get('title', '')}" for i, r in enumerate(results)]
            return "🔍 ผลการค้นหา:\n" + "\n".join(lines)

    if cmd == "help":
        return (
            "🤖 Synapse Oracle Assistant\n\n"
            "คำสั่ง:\n"
            "  /search <คำค้นหา> — ค้นหาความรู้\n"
            "  /ask <คำถาม> — ถามและตอบจากความรู้\n"
            "  /recent [scope] — เอกสารล่าสุด\n"
            "  /stats — สถิติฐานความรู้\n"
            "  /scopes — รายการ scope\n"
            "  /help — ช่วยเหลือ\n\n"
            "ส่งข้อความปกติ → สรุปและถามก่อนบันทึก\n"
            "ถามคำถามชัดเจน → ค้นหาและตอบจากความรู้\n"
            "ตอบ 'ใช่' → ยืนยันการบันทึก\n"
            "ตอบ 'ไม่' → ยกเลิก"
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
    """Determine synapse scope from LINE event source."""
    source = event.get("source", {})
    source_type = source.get("type", "user")
    if source_type == "group":
        return f"line-group-{source.get('groupId', 'unknown')[:16]}"
    if source_type == "room":
        return f"line-room-{source.get('roomId', 'unknown')[:16]}"
    return f"line-user-{source.get('userId', 'unknown')[:16]}"


def _chat_id_from_event(event: dict) -> str:
    """Get a chat identifier for pending review lookup."""
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


# ─── Knowledge capture pipeline ─────────────────────────────────

async def _build_pending_review(
    event: dict,
    settings,
) -> tuple[dict | None, str]:
    """Build a pending review from a LINE event.

    Returns (review_dict, skip_reason).
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
        return None, ""

    if event.get("type") != "message":
        return None, ""

    scope = event_to_scope(event)
    source_type = source.get("type", "user")

    content = ""
    title = "LINE Message"
    needs_summary = False

    if msg_type == "text":
        content = message.get("text", "")
        if len(content) < 10:
            return None, "ข้อความสั้นเกินไป (ต้องมีอย่างน้อย 10 ตัวอักษร)"
        if len(content) > 100:
            needs_summary = True
            title = "LINE Text (สรุป)"
        else:
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
                    needs_summary = True
                    title = "LINE Image (OCR)"
                else:
                    return None, ""
            except Exception as e:
                return None, ""
        else:
            content = "[image: no access token for download]"
            title = "LINE Image"

    elif msg_type == "video":
        channel_token = getattr(settings, "line_channel_access_token", "")
        if channel_token and message_id:
            try:
                video_bytes = await _download_line_media(message_id, channel_token)
                content = (
                    f"[video: {len(video_bytes)} bytes]\n"
                    "Video transcription not yet implemented."
                )
                title = "LINE Video (รอสรุป)"
            except Exception as e:
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
                content = (
                    f"[audio: {len(audio_bytes)} bytes]\n"
                    "Audio transcription not yet implemented."
                )
                title = "LINE Audio (รอสรุป)"
            except Exception as e:
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

    summary = ""
    if needs_summary and content:
        summary = await _summarize_text(content, settings)

    # --- Task detection ---
    task_info = _extract_task_info(content) if msg_type == "text" else None
    doc_type = "task" if task_info else "note"
    concepts = ["line", f"line_{msg_type}", f"line_{source_type}"]
    tags = ["line", source_type, msg_type]
    if task_info:
        concepts.append("task")
        tags.append("task")

    metadata = {
        "source": {
            "platform": "line",
            "type": source_type,
            "id": source.get("groupId") or source.get("roomId") or user_id or "",
            "user_id": user_id,
        },
        "message_id": message_id,
        "message_type": msg_type,
        "reply_token": reply_token,
        "timestamp": timestamp,
    }
    if task_info:
        metadata["task"] = {
            "due_date": task_info.get("due_date"),
            "status": task_info.get("status") or "pending",
            "assignee": task_info.get("assignee"),
            "priority": task_info.get("priority") or "normal",
        }

    line_source = f"line-{source_type}"
    return {
        "title": title,
        "content": content,
        "summary": summary,
        "scope": scope,
        "doc_type": doc_type,
        "source_type": line_source,
        "source_project": "line-integration",
        "oracle_name": "line-bot",
        "tags": tags,
        "concepts": concepts,
        "metadata": {**metadata, "source_type": line_source},
        "reply_token": reply_token,
        "user_id": user_id,
        "chat_id": chat_id,
    }, ""


# ─── Main event processor ──────────────────────────────────────

async def process_line_events(
    events: list[dict],
    pg,
    access_token: str = "",
    settings = None,
) -> dict:
    """Process LINE events: chatbot + knowledge capture + commands.

    Group/room = SILENT (auto-capture, no replies).
    Task = supersede if same title+scope exists.

    Returns stats dict.
    """
    answered = 0
    commands = 0
    created = 0
    pushed = 0
    replied = 0
    skipped = 0
    superseded = 0

    for event in events:
        if event.get("type") != "message":
            continue

        message = event.get("message", {})
        msg_type = message.get("type", "")
        source = event.get("source", {})
        user_id = source.get("userId", "")
        chat_id = _chat_id_from_event(event)
        reply_token = event.get("replyToken", "")
        scope = event_to_scope(event)
        silent = _is_group_chat(event)

        # ─── Silent mode: group/room = auto-capture, no interaction ───
        if silent:
            review, skip_reason = await _build_pending_review(event, settings)
            if review is None:
                skipped += 1
                continue

            # Task supersede check
            if review["doc_type"] == "task":
                existing = await _find_existing_task(pg, review["title"], scope)
                if existing:
                    try:
                        new_content = review["content"]
                        if review.get("summary"):
                            new_content = f"{review['summary']}\n\n{new_content}"
                        await pg.supersede(
                            existing["id"],
                            new_content,
                            reason="task_update",
                            new_title=review["title"],
                        )
                        superseded += 1
                        continue
                    except Exception as e:
                        log.warning("Task supersede failed: %s", e)

            # Auto-push without confirmation
            try:
                from src.ingest.push import Push
                from src.db.qdrant_store import QdrantStore
                from src.embed.ollama import OllamaEmbedder
                qdrant = None
                embedder = None
                try:
                    qdrant = QdrantStore(settings)
                    await qdrant.connect()
                    embedder = OllamaEmbedder(settings)
                except Exception:
                    pass
                pusher = Push(pg, qdrant, embedder)
                result = await pusher.push_text(
                    title=review["title"],
                    content=review["content"],
                    scope=review["scope"],
                    doc_type=review["doc_type"],
                    source_type=review["source_type"],
                    source_project=review["source_project"],
                    oracle_name=review["oracle_name"],
                    tags=review["tags"],
                    concepts=review["concepts"],
                )
                if result.get("status") == "duplicate":
                    skipped += 1
                else:
                    pushed += 1
            except Exception as e:
                log.warning("Silent auto-push failed: %s", e)
                skipped += 1
            continue

        # ─── DM mode: interactive chatbot ──────────────────────────
        if msg_type == "text":
            text = message.get("text", "")

            # 1A. Confirmation replies
            confirmation = _is_confirmation_reply(text)
            if confirmation:
                action, _ = confirmation
                pending = None
                if chat_id:
                    pending = await pg.get_pending_review_for_chat(chat_id)
                if not pending and user_id:
                    pending = await pg.get_pending_review_for_user(user_id)

                if pending:
                    if action == "confirm":
                        confirmed = await pg.confirm_pending_review(pending["id"])
                        if confirmed["status"] == "confirmed":
                            try:
                                from src.ingest.push import Push
                                from src.db.qdrant_store import QdrantStore
                                from src.embed.ollama import OllamaEmbedder
                                qdrant = None
                                embedder = None
                                try:
                                    qdrant = QdrantStore(settings)
                                    await qdrant.connect()
                                    embedder = OllamaEmbedder(settings)
                                except Exception:
                                    pass
                                pusher = Push(pg, qdrant, embedder)
                                await pusher.push_text(
                                    title=confirmed["title"],
                                    content=confirmed["content"],
                                    scope=confirmed["scope"],
                                    doc_type=confirmed["doc_type"],
                                    source_type=confirmed["source_type"],
                                    source_project=confirmed["source_project"],
                                    oracle_name=confirmed["oracle_name"],
                                    tags=confirmed["tags"],
                                    concepts=confirmed["concepts"],
                                )
                                pushed += 1
                                if access_token and reply_token:
                                    await _send_reply(access_token, reply_token, "✅ บันทึกความรู้เรียบร้อยแล้ว")
                                    replied += 1
                            except Exception as e:
                                log.warning("Failed to push confirmed review: %s", e)
                                if access_token and reply_token:
                                    await _send_reply(access_token, reply_token, f"❌ บันทึกไม่สำเร็จ: {e}")
                                    replied += 1
                    elif action == "cancel":
                        await pg.cancel_pending_review(pending["id"])
                        if access_token and reply_token:
                            await _send_reply(access_token, reply_token, "❌ ยกเลิกการบันทึกแล้ว")
                            replied += 1
                        skipped += 1
                    continue
                else:
                    if access_token and reply_token:
                        await _send_reply(access_token, reply_token, "ไม่พบรายการรอการยืนยัน")
                        replied += 1
                    continue

            # 1B. Commands
            cmd_result = _is_command(text)
            if cmd_result:
                cmd, args = cmd_result
                reply = await _handle_command(cmd, args, pg, settings, scope=scope)
                if access_token and reply_token:
                    await _send_reply(access_token, reply_token, reply)
                    replied += 1
                commands += 1
                continue

        # 2. Skip stickers
        if msg_type == "sticker":
            skipped += 1
            if access_token and reply_token:
                await _send_reply(access_token, reply_token, "สติ๊กเกอร์ไม่สามารถบันทึกเป็นความรู้ได้")
                replied += 1
            continue

        # 3. Knowledge capture (DM)
        review, skip_reason = await _build_pending_review(event, settings)
        if review is None:
            skipped += 1
            if access_token and reply_token and skip_reason:
                await _send_reply(access_token, reply_token, skip_reason)
                replied += 1
            elif access_token and reply_token and msg_type == "text":
                text = message.get("text", "")
                if len(text) >= 10:
                    chat_reply = await _chat_with_user(text, settings)
                    await _send_reply(access_token, reply_token, chat_reply)
                    replied += 1
            continue

        # Task supersede check for DM too
        if review["doc_type"] == "task":
            existing = await _find_existing_task(pg, review["title"], scope)
            if existing:
                try:
                    new_content = review["content"]
                    if review.get("summary"):
                        new_content = f"{review['summary']}\n\n{new_content}"
                    await pg.supersede(
                        existing["id"],
                        new_content,
                        reason="task_update",
                        new_title=review["title"],
                    )
                    superseded += 1
                    if access_token and reply_token:
                        await _send_reply(access_token, reply_token, "📝 Task updated (superseded)")
                        replied += 1
                    continue
                except Exception as e:
                    log.warning("Task supersede failed: %s", e)

        try:
            result = await pg.create_pending_review(review)
            created += 1

            if access_token and reply_token:
                display = review.get("summary") or review["content"][:300]
                if len(review["content"]) > 300:
                    display += "..."
                display = _to_bullets(display)
                msg = (
                    f"📝 สรุป:\n{display}\n\n"
                    f"ต้องการบันทึกไหม? (ตอบ 'ใช่' หรือ 'ไม่')"
                )
                await _send_reply(access_token, reply_token, msg)
                replied += 1
        except Exception as e:
            log.warning("Failed to create pending review: %s", e)
            skipped += 1
            if access_token and reply_token:
                await _send_reply(access_token, reply_token, f"❌ ไม่สามารถสร้างรายการรอยืนยันได้: {e}")
                replied += 1

    return {
        "answered": answered,
        "commands": commands,
        "created": created,
        "pushed": pushed,
        "replied": replied,
        "skipped": skipped,
        "superseded": superseded,
    }


async def _send_reply(access_token: str, reply_token: str, text: str) -> None:
    """Send a reply message via LINE Messaging API."""
    import httpx

    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        log.debug("LINE reply sent: %s", resp.status_code)
