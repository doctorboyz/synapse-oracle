"""Tests for LINE webhook handler v2 — full chatbot features."""

import pytest

from src.api.line_handler import (
    _is_command,
    _is_confirmation_reply,
    _is_question,
    event_to_scope,
    verify_line_signature,
)


class TestIsCommand:
    def test_search_with_args(self):
        assert _is_command("/search docker compose") == ("search", "docker compose")

    def test_search_no_args(self):
        assert _is_command("/search") == ("search", "")

    def test_stats(self):
        assert _is_command("/stats") == ("stats", "")

    def test_recent_with_scope(self):
        assert _is_command("/recent infra-oracle") == ("recent", "infra-oracle")

    def test_help(self):
        assert _is_command("/help") == ("help", "")

    def test_invalid_command(self):
        assert _is_command("/invalid") is None

    def test_not_a_command(self):
        assert _is_command("hello world") is None


class TestIsQuestion:
    def test_question_mark(self):
        assert _is_question("What is docker?") is True

    def test_thai_question_mark(self):
        assert _is_question("docker คืออะไร?") is True

    def test_who(self):
        assert _is_question("who created this") is True

    def test_how_to(self):
        assert _is_question("how to deploy") is True

    def test_thai_what_explicit(self):
        assert _is_question("คืออะไร") is True

    def test_thai_what_not_prefix(self):
        # "นี่คืออะไร" ไม่ขึ้นต้นด้วยคำถาม → knowledge capture
        assert _is_question("นี่คืออะไร") is False

    def test_thai_where_not_prefix(self):
        # "อยู่ที่ไหน" ไม่ขึ้นต้นด้วย "ที่ไหน" → knowledge capture
        assert _is_question("อยู่ที่ไหน") is False

    def test_thai_why(self):
        assert _is_question("ทำไมถึงเป็นแบบนี้") is True

    def test_thai_how(self):
        assert _is_question("ยังไง") is True

    def test_thai_please_tell(self):
        assert _is_question("ช่วยบอกหน่อย") is True

    def test_thai_want_to_know(self):
        assert _is_question("อยากรู้ว่า") is True

    def test_not_a_question(self):
        assert _is_question("docker compose is great") is False

    def test_statement_with_question_word(self):
        # "how" appears but not as a question
        assert _is_question("this is how we do it") is False


class TestHandleCommand:
    @pytest.mark.asyncio
    async def test_help_command(self, clean_pg, monkeypatch):
        from src.api.line_handler import _handle_command
        from src.config import Settings

        reply = await _handle_command("help", "", clean_pg, Settings(), scope="test")
        assert "Synapse Oracle Assistant" in reply
        assert "/search" in reply

    @pytest.mark.asyncio
    async def test_stats_command(self, clean_pg):
        from src.api.line_handler import _handle_command
        from src.config import Settings

        reply = await _handle_command("stats", "", clean_pg, Settings(), scope="test")
        assert "สถิติ" in reply
        assert "เอกสาร" in reply

    @pytest.mark.asyncio
    async def test_scopes_command(self, clean_pg):
        from src.api.line_handler import _handle_command
        from src.config import Settings

        reply = await _handle_command("scopes", "", clean_pg, Settings(), scope="test")
        assert "Scopes" in reply or "scope" in reply.lower()

    @pytest.mark.asyncio
    async def test_search_command_with_results(self, clean_pg, monkeypatch):
        from src.api.line_handler import _handle_command
        from src.config import Settings

        # Add a doc first
        await clean_pg.add(title="Docker Guide", content="docker compose tips", scope="test")
        reply = await _handle_command("search", "docker", clean_pg, Settings(), scope="test")
        assert "Docker Guide" in reply

    @pytest.mark.asyncio
    async def test_search_command_no_results(self, clean_pg):
        from src.api.line_handler import _handle_command
        from src.config import Settings

        reply = await _handle_command("search", "xyzabc", clean_pg, Settings(), scope="test")
        assert "ไม่พบ" in reply or "no results" in reply.lower()

    @pytest.mark.asyncio
    async def test_recent_command(self, clean_pg):
        from src.api.line_handler import _handle_command
        from src.config import Settings

        await clean_pg.add(title="Recent Doc", content="content", scope="test")
        reply = await _handle_command("recent", "test", clean_pg, Settings(), scope="test")
        assert "Recent Doc" in reply

    @pytest.mark.asyncio
    async def test_ask_command_no_args(self, clean_pg):
        from src.api.line_handler import _handle_command
        from src.config import Settings

        reply = await _handle_command("ask", "", clean_pg, Settings(), scope="test")
        assert "ใช้: /ask" in reply

    @pytest.mark.asyncio
    async def test_ask_command_with_results(self, clean_pg, monkeypatch):
        from src.api.line_handler import _handle_command
        from src.config import Settings

        await clean_pg.add(title="Docker Tips", content="Use docker compose", scope="test")

        async def mock_chat(*args, **kwargs):
            return "Use docker compose for local dev"

        monkeypatch.setattr("src.llm.openrouter_client.OpenRouterClient.chat", mock_chat)
        monkeypatch.setattr("src.llm.openrouter_client.OpenRouterClient.enabled", True)

        reply = await _handle_command("ask", "how to use docker", clean_pg, Settings(), scope="test")
        assert "Docker Tips" in reply

    @pytest.mark.asyncio
    async def test_ask_command_no_results(self, clean_pg):
        from src.api.line_handler import _handle_command
        from src.config import Settings

        reply = await _handle_command("ask", "xyzabc123", clean_pg, Settings(), scope="test")
        assert "ไม่พบ" in reply


class TestAnswerQuestion:
    @pytest.mark.asyncio
    async def test_answer_with_results(self, clean_pg, monkeypatch):
        from src.api.line_handler import _answer_question
        from src.config import Settings

        await clean_pg.add(title="Docker Tips", content="Use docker compose for local dev", scope="test")
        settings = Settings()

        # Mock OpenRouter chat to avoid real API calls
        async def mock_chat(*args, **kwargs):
            return "Use docker compose"

        monkeypatch.setattr("src.llm.openrouter_client.OpenRouterClient.chat", mock_chat)
        monkeypatch.setattr("src.llm.openrouter_client.OpenRouterClient.enabled", True)

        reply = await _answer_question("how to use docker?", clean_pg, settings, scope="test")
        assert "Docker Tips" in reply

    @pytest.mark.asyncio
    async def test_answer_no_results(self, clean_pg):
        from src.api.line_handler import _answer_question
        from src.config import Settings

        reply = await _answer_question("xyzabc123", clean_pg, Settings(), scope="test")
        assert "ไม่พบ" in reply or "not found" in reply.lower()


class TestProcessLineEventsFullFlow:
    @pytest.mark.asyncio
    async def test_command_search(self, clean_pg, monkeypatch):
        from src.api.line_handler import process_line_events
        from src.config import Settings

        await clean_pg.add(title="Guide", content="docker tips", scope="shared")
        monkeypatch.setattr("src.api.line_handler._send_reply", lambda *a, **k: None)

        events = [
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": {"type": "text", "text": "/search docker", "id": "1"},
                "replyToken": "rt1",
                "timestamp": 123,
            }
        ]
        stats = await process_line_events(events, clean_pg, access_token="", settings=Settings())
        assert stats["commands"] == 1
        assert stats["answered"] == 0

    @pytest.mark.asyncio
    async def test_question_text_goes_to_capture(self, clean_pg, monkeypatch):
        from src.api.line_handler import process_line_events
        from src.config import Settings

        monkeypatch.setattr("src.api.line_handler._send_reply", lambda *a, **k: None)

        events = [
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": {"type": "text", "text": "docker คืออะไร?", "id": "1"},
                "replyToken": "rt1",
                "timestamp": 123,
            }
        ]
        stats = await process_line_events(events, clean_pg, access_token="", settings=Settings())
        # Without auto-detect, questions go to knowledge capture
        assert stats["answered"] == 0
        assert stats["created"] == 1

    @pytest.mark.asyncio
    async def test_ask_command_flow(self, clean_pg, monkeypatch):
        from src.api.line_handler import process_line_events
        from src.config import Settings

        await clean_pg.add(title="Docker Guide", content="docker compose v2", scope="shared")
        monkeypatch.setattr("src.api.line_handler._send_reply", lambda *a, **k: None)

        async def mock_chat(*args, **kwargs):
            return "Mock answer"
        monkeypatch.setattr("src.llm.openrouter_client.OpenRouterClient.chat", mock_chat)
        monkeypatch.setattr("src.llm.openrouter_client.OpenRouterClient.enabled", True)

        events = [
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": {"type": "text", "text": "/ask docker คืออะไร", "id": "1"},
                "replyToken": "rt1",
                "timestamp": 123,
            }
        ]
        stats = await process_line_events(events, clean_pg, access_token="", settings=Settings())
        assert stats["commands"] == 1
        assert stats["answered"] == 0  # commands counted separately
        assert stats["created"] == 0

    @pytest.mark.asyncio
    async def test_knowledge_capture_flow(self, clean_pg, monkeypatch):
        from src.api.line_handler import process_line_events
        from src.config import Settings

        monkeypatch.setattr("src.api.line_handler._send_reply", lambda *a, **k: None)

        events = [
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": {"type": "text", "text": "This is a message about testing the bot", "id": "1"},
                "replyToken": "rt1",
                "timestamp": 123,
            }
        ]
        stats = await process_line_events(events, clean_pg, access_token="", settings=Settings())
        assert stats["created"] == 1

    @pytest.mark.asyncio
    async def test_confirmation_yes(self, clean_pg, monkeypatch):
        from src.api.line_handler import process_line_events
        from src.config import Settings

        monkeypatch.setattr("src.api.line_handler._send_reply", lambda *a, **k: None)

        # Create pending review first
        review = {
            "title": "Test",
            "content": "content",
            "summary": "",
            "scope": "line-user-U1",
            "doc_type": "note",
            "source_type": "line",
            "source_project": "line-integration",
            "oracle_name": "line-bot",
            "tags": ["line"],
            "concepts": ["line"],
            "metadata": {},
            "reply_token": "rt-old",
            "user_id": "U1",
            "chat_id": "U1",
        }
        result = await clean_pg.create_pending_review(review)

        events = [
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": {"type": "text", "text": "ใช่", "id": "2"},
                "replyToken": "rt-new",
                "timestamp": 456,
            }
        ]
        stats = await process_line_events(events, clean_pg, access_token="", settings=Settings())
        assert stats["pushed"] == 1

    @pytest.mark.asyncio
    async def test_sticker_skip(self, clean_pg, monkeypatch):
        from src.api.line_handler import process_line_events
        from src.config import Settings

        monkeypatch.setattr("src.api.line_handler._send_reply", lambda *a, **k: None)

        events = [
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": {"type": "sticker", "id": "1"},
                "replyToken": "rt1",
                "timestamp": 123,
            }
        ]
        stats = await process_line_events(events, clean_pg, access_token="", settings=Settings())
        assert stats["skipped"] == 1
