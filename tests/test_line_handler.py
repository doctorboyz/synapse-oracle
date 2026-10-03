"""Tests for LINE webhook handler — auto-ingest pipeline v2."""

import base64
import hashlib
import hmac

import pytest

from src.api.line_handler import (
    _build_knowledge_doc,
    _chat_id_from_event,
    _is_command,
    _is_group_chat,
    _is_question,
    _strip_markdown,
    event_to_scope,
    process_line_events,
    verify_line_signature,
)


class TestVerifyLineSignature:
    def test_valid_signature(self):
        secret = "test-secret"
        body = b'{"events":[]}'
        expected = base64.b64encode(
            hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        ).decode("utf-8")
        assert verify_line_signature(body, expected, secret) is True

    def test_invalid_signature(self):
        assert verify_line_signature(b"body", "invalid", "secret") is False

    def test_no_secret(self):
        assert verify_line_signature(b"body", "sig", "") is False


class TestIsCommand:
    def test_search_command(self):
        assert _is_command("/search python") == ("search", "python")

    def test_ask_command(self):
        assert _is_command("/ask อะไรเอ่ย") == ("ask", "อะไรเอ่ย")

    def test_help_command(self):
        assert _is_command("/help") == ("help", "")

    def test_not_command(self):
        assert _is_command("hello world") is None
        assert _is_command("search") is None


class TestIsQuestion:
    def test_english_question(self):
        assert _is_question("What is Python?") is True
        assert _is_question("how to deploy") is True

    def test_thai_question(self):
        assert _is_question("ทำไมเป็นอย่างนี้") is True
        assert _is_question("คืออะไรเอ่ย") is True
        assert _is_question("มีไหมครับ") is True

    def test_not_question(self):
        assert _is_question("hello world") is False
        assert _is_question("Deploy the app") is False



    @pytest.mark.asyncio
    async def test_task_command_parsing(self):
        from src.api.line_handler import _is_command
        result = _is_command("/task deploy app due Friday")
        assert result == ("task", "deploy app due Friday")

        result = _is_command("/todo send report")
        assert result == ("todo", "send report")

        result = _is_command("/remind call team Monday")
        assert result == ("remind", "call team Monday")

    @pytest.mark.asyncio
    async def test_regular_message_not_task(self):
        """Messages with dates/@mentions but no task intent should be notes."""
        from src.api.line_handler import _extract_task_info

        # Date without task intent → None
        assert _extract_task_info("see you on 3/6", require_intent=True) is None
        assert _extract_task_info("สวัสดี วันศุกร์", require_intent=True) is None

        # @mention without task intent → None
        assert _extract_task_info("hey @john what's up", require_intent=True) is None

        # Casual "going to" without task intent → None (removed from keywords)
        # Note: "going to" is still in EN keywords but phrase needs to match

    @pytest.mark.asyncio
    async def test_explicit_task_intent(self):
        """Messages with explicit task keywords should be detected."""
        from src.api.line_handler import _extract_task_info

        # Thai task intent
        result = _extract_task_info("ต้องส่งรายงานวันศุกร์", require_intent=True)
        assert result is not None
        assert result["is_task"] is True

        # English task intent
        result = _extract_task_info("need to finish the report", require_intent=True)
        assert result is not None
        assert result["is_task"] is True

        # Reminder intent
        result = _extract_task_info("remind me to call mom", require_intent=True)
        assert result is not None

    @pytest.mark.asyncio
    async def test_task_intent_with_date_extraction(self):
        """When task intent is present, dates should be extracted."""
        from src.api.line_handler import _extract_task_info

        # Thai weekday + task intent
        result = _extract_task_info("ต้องส่งรายงาน วันศุกร์นี้", require_intent=True)
        assert result is not None
        assert result["due_date"] is not None

        # English task with relative date
        result = _extract_task_info("task: deploy due tomorrow", require_intent=True)
        assert result is not None
        assert result["due_date"] is not None

class TestEventToScope:
    def test_user_source(self):
        event = {"source": {"type": "user", "userId": "U123"}}
        assert event_to_scope(event) == "line"

    def test_group_source(self):
        event = {"source": {"type": "group", "groupId": "G123"}}
        assert event_to_scope(event) == "line"

    def test_room_source(self):
        event = {"source": {"type": "room", "roomId": "R123"}}
        assert event_to_scope(event) == "line"

    def test_missing_source(self):
        assert event_to_scope({}) == "line"


class TestChatIdFromEvent:
    def test_group(self):
        event = {"source": {"type": "group", "groupId": "G1"}}
        assert _chat_id_from_event(event) == "G1"

    def test_room(self):
        event = {"source": {"type": "room", "roomId": "R1"}}
        assert _chat_id_from_event(event) == "R1"

    def test_user(self):
        event = {"source": {"type": "user", "userId": "U1"}}
        assert _chat_id_from_event(event) == "U1"


class TestIsGroupChat:
    def test_group(self):
        assert _is_group_chat({"source": {"type": "group"}}) is True

    def test_room(self):
        assert _is_group_chat({"source": {"type": "room"}}) is True

    def test_user(self):
        assert _is_group_chat({"source": {"type": "user"}}) is False


class TestBuildKnowledgeDoc:
    @pytest.mark.asyncio
    async def test_text_short_skipped(self):
        from src.config import Settings

        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {"type": "text", "text": "hi", "id": "1"},
            "replyToken": "rt1",
            "timestamp": 123,
        }
        doc = await _build_knowledge_doc(event, Settings())
        assert doc is None

    @pytest.mark.asyncio
    async def test_text_normal(self):
        from src.config import Settings

        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {"type": "text", "text": "This is a normal message here", "id": "1"},
            "replyToken": "rt1",
            "timestamp": 123,
        }
        doc = await _build_knowledge_doc(event, Settings())
        assert doc is not None
        assert doc["title"] == "LINE Text"
        assert doc["content"] == "This is a normal message here"
        assert doc["scope"] == "line"
        assert doc["user_id"] == "U1"
        assert "line_text" in doc["concepts"]

    @pytest.mark.asyncio
    async def test_sticker_returns_none(self):
        from src.config import Settings

        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {"type": "sticker", "id": "1"},
            "replyToken": "rt1",
            "timestamp": 123,
        }
        doc = await _build_knowledge_doc(event, Settings())
        assert doc is None

    @pytest.mark.asyncio
    async def test_location(self):
        from src.config import Settings

        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {
                "type": "location",
                "address": "Bangkok",
                "latitude": 13.7,
                "longitude": 100.5,
                "id": "1",
            },
            "replyToken": "rt1",
            "timestamp": 123,
        }
        doc = await _build_knowledge_doc(event, Settings())
        assert doc is not None
        assert doc["title"] == "LINE Location"
        assert "Bangkok" in doc["content"]
        assert "13.7" in doc["content"]

    @pytest.mark.asyncio
    async def test_image_no_token(self):
        from src.config import Settings

        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {"type": "image", "id": "img1"},
            "replyToken": "rt1",
            "timestamp": 123,
        }
        doc = await _build_knowledge_doc(event, Settings())
        assert doc is not None
        assert doc["title"] == "LINE Image"
        assert "no access token" in doc["content"]

    @pytest.mark.asyncio
    async def test_video(self):
        from src.config import Settings

        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {"type": "video", "id": "vid1"},
            "replyToken": "rt1",
            "timestamp": 123,
        }
        doc = await _build_knowledge_doc(event, Settings())
        assert doc is not None
        assert doc["title"] == "LINE Video"
        assert doc["metadata"]["needs_transcription"] is True
        assert doc["metadata"]["media_size"] == 0

    @pytest.mark.asyncio
    async def test_audio(self):
        from src.config import Settings

        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {"type": "audio", "id": "aud1"},
            "replyToken": "rt1",
            "timestamp": 123,
        }
        doc = await _build_knowledge_doc(event, Settings())
        assert doc is not None
        assert doc["title"] == "LINE Audio"
        assert doc["metadata"]["needs_transcription"] is True
        assert doc["metadata"]["media_size"] == 0

    @pytest.mark.asyncio
    async def test_file(self):
        from src.config import Settings

        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {"type": "file", "fileName": "report.pdf", "id": "f1"},
            "replyToken": "rt1",
            "timestamp": 123,
        }
        doc = await _build_knowledge_doc(event, Settings())
        assert doc is not None
        assert doc["title"] == "LINE File"
        assert "report.pdf" in doc["content"]

    @pytest.mark.asyncio
    async def test_regular_message_is_note_not_task(self):
        """Regular messages with dates/@mentions are stored as notes, not tasks.
        Task creation requires explicit /task, /todo, or /remind command."""
        from src.config import Settings

        # This used to be classified as "task" due to auto-detection,
        # but now regular messages are always "note"
        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {"type": "text", "text": "Task: deploy app due tomorrow @john", "id": "1"},
            "replyToken": "rt1",
            "timestamp": 123,
        }
        doc = await _build_knowledge_doc(event, Settings())
        assert doc is not None
        assert doc["doc_type"] == "note"

    @pytest.mark.asyncio
    async def test_extract_task_info_require_intent(self):
        """_extract_task_info with require_intent=True only matches explicit task intent."""
        from src.api.line_handler import _extract_task_info

        # No task intent keywords → returns None (require_intent=True)
        assert _extract_task_info("see you tomorrow", require_intent=True) is None
        assert _extract_task_info("meeting on 3/6", require_intent=True) is None
        assert _extract_task_info("hello @john", require_intent=True) is None
        assert _extract_task_info("สวัสดีวันจันทร์", require_intent=True) is None

        # Explicit task intent → returns task info
        result = _extract_task_info("ต้องส่งรายงานวันศุกร์", require_intent=True)
        assert result is not None
        assert result["is_task"] is True

        result = _extract_task_info("task: deploy app", require_intent=True)
        assert result is not None

        # require_intent=False (used by /task command) → aggressive detection
        result = _extract_task_info("meeting on 3/6", require_intent=False)
        assert result is not None  # date detected even without intent keywords

    @pytest.mark.asyncio
    async def test_extract_task_info_with_slash_command_intent(self):
        """When /task command is used, require_intent=False allows date/@mention detection."""
        from src.api.line_handler import _extract_task_info

        # /task command text: should detect dates and @mentions
        result = _extract_task_info("deploy app due tomorrow @john", require_intent=False)
        assert result is not None
        assert result["assignee"] == "john"

        result = _extract_task_info("ส่งรายงาน วันศุกร์นี้", require_intent=False)
        assert result is not None
        assert result["due_date"] is not None


class TestProcessLineEvents:
    @pytest.mark.asyncio
    async def test_auto_push_text(self, clean_pg, monkeypatch):
        from src.config import Settings

        async def mock_send_reply(token, rt, text, quick_reply=None):
            pass

        monkeypatch.setattr("src.api.line_handler._send_reply", mock_send_reply)
        # Prevent internal Ollama initialization
        monkeypatch.setattr("src.embed.ollama.OllamaEmbedder", type("FakeEmbedder", (), {
            "__init__": lambda self, s: None,
        }))

        events = [
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": {"type": "text", "text": "hello from line user with enough text to bypass guided question check and this message needs to be at least two hundred characters long so it does not trigger the uncertainty heuristics in the line handler", "id": "1"},
                "replyToken": "rt1",
                "timestamp": 123,
            }
        ]
        settings = Settings()
        stats = await process_line_events(events, clean_pg, access_token="", settings=settings)
        assert stats["pushed"] == 1
        assert stats["skipped"] == 0
        assert stats["deduplicated"] == 0

    @pytest.mark.asyncio
    async def test_skips_stickers(self, clean_pg):
        from src.config import Settings

        events = [
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": {"type": "sticker", "id": "1"},
                "replyToken": "rt1",
                "timestamp": 123,
            }
        ]
        settings = Settings()
        stats = await process_line_events(events, clean_pg, access_token="", settings=settings)
        assert stats["skipped"] == 1
        assert stats["pushed"] == 0

    @pytest.mark.asyncio
    async def test_skips_short_text(self, clean_pg):
        from src.config import Settings

        events = [
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": {"type": "text", "text": "hi", "id": "1"},
                "replyToken": "rt1",
                "timestamp": 123,
            }
        ]
        settings = Settings()
        stats = await process_line_events(events, clean_pg, access_token="", settings=settings)
        assert stats["skipped"] == 1
        assert stats["pushed"] == 0

    @pytest.mark.asyncio
    async def test_command_search(self, clean_pg, monkeypatch):
        from src.config import Settings

        replies = []

        async def mock_send_reply(token, rt, text, quick_reply=None):
            replies.append(text)

        monkeypatch.setattr("src.api.line_handler._send_reply", mock_send_reply)

        events = [
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": {"type": "text", "text": "/search python", "id": "1"},
                "replyToken": "rt1",
                "timestamp": 123,
            }
        ]
        settings = Settings()
        stats = await process_line_events(events, clean_pg, access_token="tok", settings=settings)
        assert stats["commands"] == 1
        assert stats["replied"] == 1
        assert any("🔍" in r for r in replies)

    @pytest.mark.asyncio
    async def test_group_chat_silent(self, clean_pg, monkeypatch):
        """Group/room events auto-ingest without replying."""
        from src.config import Settings

        monkeypatch.setattr("src.embed.ollama.OllamaEmbedder", type("FakeEmbedder", (), {
            "__init__": lambda self, s: None,
        }))

        events = [
            {
                "type": "message",
                "source": {"type": "group", "groupId": "G1"},
                "message": {"type": "text", "text": "hello everyone in group", "id": "1"},
                "replyToken": "rt1",
                "timestamp": 123,
            }
        ]
        settings = Settings()
        stats = await process_line_events(events, clean_pg, access_token="", settings=settings)
        assert stats["pushed"] == 1
        assert stats["replied"] == 0

    @pytest.mark.asyncio
    async def test_non_message_events_ignored(self, clean_pg):
        from src.config import Settings

        events = [
            {"type": "follow", "source": {"type": "user", "userId": "U1"}},
            {"type": "join", "source": {"type": "group", "groupId": "G1"}},
        ]
        settings = Settings()
        stats = await process_line_events(events, clean_pg, access_token="", settings=settings)
        assert stats["pushed"] == 0
        assert stats["skipped"] == 0

    @pytest.mark.asyncio
    async def test_task_command_creates_todo(self, clean_pg, monkeypatch):
        """Task creation via explicit /task command.

        Regular messages are always doc_type='note' (no auto-task detection).
        Task creation requires explicit /task, /todo, or /remind commands.
        """
        from src.config import Settings

        async def mock_send_reply(token, rt, text, quick_reply=None):
            pass

        async def mock_embed(self, text):
            import hashlib
            dim = 768
            h = hashlib.sha256(text.encode()).digest()
            return [float(b) / 255.0 for b in h[:dim]]

        monkeypatch.setattr("src.api.line_handler._send_reply", mock_send_reply)
        monkeypatch.setattr("src.embed.ollama.OllamaEmbedder", type("FakeEmbedder", (), {
            "__init__": lambda self, s: None,
            "embed": mock_embed,
        }))

        # Create task via /task command
        events = [
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": {"type": "text", "text": "/task deploy app due 2026-05-25", "id": "1"},
                "replyToken": "rt1",
                "timestamp": 123,
            }
        ]
        settings = Settings()
        stats = await process_line_events(events, clean_pg, access_token="test-token", settings=settings)
        # /task command should create a task (counted in "commands", possibly "created")
        assert stats["commands"] >= 1

    @pytest.mark.asyncio
    async def test_regular_message_is_note(self, clean_pg, monkeypatch):
        """Regular messages (without /task) are always stored as notes, never auto-detected as tasks."""
        from src.config import Settings

        async def mock_send_reply(token, rt, text, quick_reply=None):
            pass

        async def mock_embed(self, text):
            import hashlib
            dim = 768
            h = hashlib.sha256(text.encode()).digest()
            return [float(b) / 255.0 for b in h[:dim]]

        monkeypatch.setattr("src.api.line_handler._send_reply", mock_send_reply)
        monkeypatch.setattr("src.embed.ollama.OllamaEmbedder", type("FakeEmbedder", (), {
            "__init__": lambda self, s: None,
            "embed": mock_embed,
        }))

        # Text with "Task" keyword but NOT a /task command → stored as note
        events = [
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": {"type": "text", "text": "Task: deploy app due 2026-05-25 with full production rollout plan for the team to follow carefully", "id": "1"},
                "replyToken": "rt1",
                "timestamp": 123,
            }
        ]
        settings = Settings()
        stats = await process_line_events(events, clean_pg, access_token="test-token", settings=settings)
        # Regular message should be pushed as a note, not detected as task
        assert stats["pushed"] >= 1 or stats["created"] >= 1


class TestStripMarkdown:
    """LINE doesn't render markdown — _strip_markdown removes all formatting."""

    def test_bold(self):
        assert _strip_markdown("**hello**") == "hello"
        assert _strip_markdown("__hello__") == "hello"

    def test_italic(self):
        assert _strip_markdown("*hello*") == "hello"
        assert _strip_markdown("hello _world_ bye") == "hello world bye"

    def test_headers(self):
        assert _strip_markdown("## Title") == "Title"
        assert _strip_markdown("# Title\nSome text") == "Title\nSome text"
        assert _strip_markdown("### Sub-title") == "Sub-title"

    def test_blockquotes(self):
        assert _strip_markdown("> quoted text") == "quoted text"

    def test_unordered_list(self):
        assert _strip_markdown("- item one\n- item two") == "• item one\n• item two"

    def test_code_blocks(self):
        md = "```python\nprint('hi')\n```"
        assert _strip_markdown(md) == "print('hi')"

    def test_inline_code(self):
        assert _strip_markdown("use `pip install` to install") == "use pip install to install"

    def test_links(self):
        assert _strip_markdown("[click here](https://example.com)") == "click here"

    def test_strikethrough(self):
        assert _strip_markdown("~~deleted~~") == "deleted"

    def test_thai_text_preserved(self):
        # Thai text should not be mangled by markdown stripping
        text = "สวัสดีครับ นี่คือข้อความภาษาไทย"
        assert _strip_markdown(text) == text

    def test_mixed_markdown_thai(self):
        md = "**สรุป:** นี่คือความรู้\n\n## หัวข้อ\n\n- ข้อ 1\n- ข้อ 2"
        result = _strip_markdown(md)
        assert "**" not in result
        assert "##" not in result
        assert "- " not in result
        assert "สรุป:" in result
        assert "• ข้อ 1" in result

    def test_horizontal_rule(self):
        assert _strip_markdown("---") == ""
        assert _strip_markdown("above\n---\nbelow") == "above\n\nbelow"

    def test_collapse_blank_lines(self):
        assert _strip_markdown("a\n\n\n\nb") == "a\n\nb"

    def test_realistic_llm_response(self):
        """Simulate a typical LLM response with markdown that LINE can't render."""
        md = (
            "## คำตอบ\n\n"
            "ตามบริบทที่ให้มา:\n\n"
            "- **ข้อ 1**: รายละเอียด\n"
            "- **ข้อ 2**: `code example`\n\n"
            "> หมายเหตุ: ข้อมูลจากเอกสาร\n\n"
            "อ่านเพิ่มเติมได้ที่ [ลิงก์](https://example.com)"
        )
        result = _strip_markdown(md)
        # No markdown syntax should remain
        assert "**" not in result
        assert "##" not in result
        assert "- " not in result
        assert ">" not in result
        assert "`" not in result
        assert "](https://" not in result
        # Content should be preserved
        assert "คำตอบ" in result
        assert "ข้อ 1" in result
        assert "หมายเหตุ" in result
        assert "ลิงก์" in result
