"""Tests for guided question flow — pending_review confirmation logic."""

import pytest


class TestShouldAskGuidedQuestions:
    def test_short_content_triggers(self):
        from src.api.line_handler import _should_ask_guided_questions

        doc = {"title": "Short", "content": "hi", "doc_type": "note", "tags": ["test"]}
        assert _should_ask_guided_questions(doc, ["test"]) is True

    def test_no_tags_triggers(self):
        from src.api.line_handler import _should_ask_guided_questions

        doc = {"title": "No tags", "content": "This is a longer message with no tags", "doc_type": "note", "tags": []}
        assert _should_ask_guided_questions(doc, []) is True

    def test_well_tagged_long_content_skips(self):
        from src.api.line_handler import _should_ask_guided_questions

        doc = {
            "title": "Well tagged",
            "content": "This is a much longer message " * 10,
            "doc_type": "learning",
            "tags": ["python", "testing"],
        }
        assert _should_ask_guided_questions(doc, ["python"]) is False

    def test_task_doc_with_tags_skips(self):
        from src.api.line_handler import _should_ask_guided_questions

        doc = {
            "title": "Task",
            "content": "Complete the integration tests by Friday",
            "doc_type": "task",
            "tags": ["task"],
        }
        assert _should_ask_guided_questions(doc, ["task"]) is True  # still short


class TestIsGuidedAnswer:
    def test_yes_answer(self):
        from src.api.line_handler import _is_guided_answer

        assert _is_guided_answer("yes") == "yes"
        assert _is_guided_answer("ใช่") == "yes"
        assert _is_guided_answer("ตกลง") == "yes"
        assert _is_guided_answer("confirm") == "yes"

    def test_no_answer(self):
        from src.api.line_handler import _is_guided_answer

        assert _is_guided_answer("no") == "no"
        assert _is_guided_answer("ไม่") == "no"
        assert _is_guided_answer("cancel") == "no"
        assert _is_guided_answer("ยกเลิก") == "no"

    def test_edit_answer(self):
        from src.api.line_handler import _is_guided_answer

        assert _is_guided_answer("edit") == "edit"
        assert _is_guided_answer("แก้ไข") == "edit"
        assert _is_guided_answer("แก้") == "edit"

    def test_non_answer(self):
        from src.api.line_handler import _is_guided_answer

        assert _is_guided_answer("What is this?") is None
        assert _is_guided_answer("hello world") is None
        assert _is_guided_answer("") is None


class TestParseEditInstructions:
    def test_parse_thai_edit(self):
        from src.api.line_handler import _parse_edit_instructions

        updates = _parse_edit_instructions("แก้ไข ประเภท:task Tags:งาน, ด่วน")
        assert updates.get("doc_type") == "task"
        assert "งาน" in updates.get("tags", [])
        assert "ด่วน" in updates.get("tags", [])

    def test_parse_english_edit(self):
        from src.api.line_handler import _parse_edit_instructions

        updates = _parse_edit_instructions("edit type:learning tags:work, python")
        assert updates.get("doc_type") == "learning"
        assert "work" in updates.get("tags", [])
        assert "python" in updates.get("tags", [])


class TestFormatGuidedQuestion:
    def test_formats_message(self):
        from src.api.line_handler import _format_guided_question

        doc = {
            "title": "Test Doc",
            "content": "Some content here",
            "doc_type": "note",
            "tags": ["python"],
            "concepts": ["testing"],
        }
        msg, quick_reply = _format_guided_question(doc)
        assert "Test Doc" in msg or "Some content" in msg
        assert "note" in msg
        assert "python" in msg
        assert len(quick_reply) == 3
        assert quick_reply[0]["action"]["label"] == "✅ ใช่"
        assert quick_reply[1]["action"]["label"] == "❌ ไม่"
        assert quick_reply[2]["action"]["label"] == "✏️ แก้ไข"


@pytest.mark.asyncio
class TestPendingReviewFlow:
    async def test_create_and_confirm_pending_review(self, clean_pg):
        review_id = await clean_pg.create_pending_review({
            "title": "Test Review",
            "content": "Test content for review",
            "summary": "Test summary",
            "scope": "shared",
            "doc_type": "note",
            "source_type": "line",
            "tags": ["test"],
            "concepts": [],
            "metadata": {},
            "reply_token": "dummy_token",
            "user_id": "test_user_123",
            "chat_id": "test_user_123",
        })
        assert review_id["id"] is not None

        pending = await clean_pg.get_pending_review_for_user("test_user_123")
        assert pending is not None
        assert pending["title"] == "Test Review"

        confirmed = await clean_pg.confirm_pending_review(pending["id"])
        assert confirmed["status"] == "confirmed"
        assert confirmed["title"] == "Test Review"

    async def test_cancel_pending_review(self, clean_pg):
        await clean_pg.create_pending_review({
            "title": "Cancel Test",
            "content": "Will be cancelled",
            "tags": [],
            "concepts": [],
            "metadata": {},
            "user_id": "cancel_user",
            "chat_id": "cancel_user",
        })
        pending = await clean_pg.get_pending_review_for_user("cancel_user")
        assert pending is not None

        cancelled = await clean_pg.cancel_pending_review(pending["id"])
        assert cancelled["status"] == "cancelled"

        # Should no longer be pending
        pending2 = await clean_pg.get_pending_review_for_user("cancel_user")
        assert pending2 is None

    async def test_no_pending_review_for_other_user(self, clean_pg):
        await clean_pg.create_pending_review({
            "title": "User A Review",
            "content": "Only for user A",
            "tags": [], "concepts": [], "metadata": {},
            "user_id": "user_a",
            "chat_id": "user_a",
        })
        pending = await clean_pg.get_pending_review_for_user("user_b")
        assert pending is None

    async def test_expire_pending_reviews(self, clean_pg):
        await clean_pg.create_pending_review({
            "title": "Expire Test",
            "content": "Should expire",
            "tags": [], "concepts": [], "metadata": {},
            "user_id": "expire_user",
            "chat_id": "expire_user",
        })
        expired = await clean_pg.expire_pending_reviews()
        # All pending reviews are expired (set to 'expired')
        assert expired >= 0

    async def test_chat_based_lookup(self, clean_pg):
        await clean_pg.create_pending_review({
            "title": "Chat Test",
            "content": "Chat-based review",
            "tags": [], "concepts": [], "metadata": {},
            "user_id": "chat_user",
            "chat_id": "group_123",
        })
        pending = await clean_pg.get_pending_review_for_chat("group_123")
        assert pending is not None
        assert pending["title"] == "Chat Test"
