"""Tests for LINE webhook handler v2 — pending reviews and confirmation flow."""

import base64
import hashlib
import hmac
import json

import pytest
from fastapi import HTTPException

from src.api.line_handler import (
    _is_confirmation_reply,
    event_to_scope,
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


class TestIsConfirmationReply:
    def test_yes(self):
        assert _is_confirmation_reply("ใช่") == ("confirm", "")
        assert _is_confirmation_reply("yes") == ("confirm", "")
        assert _is_confirmation_reply("ok") == ("confirm", "")
        assert _is_confirmation_reply("YES") == ("confirm", "")

    def test_no(self):
        assert _is_confirmation_reply("ไม่") == ("cancel", "")
        assert _is_confirmation_reply("no") == ("cancel", "")
        assert _is_confirmation_reply("cancel") == ("cancel", "")

    def test_edit(self):
        assert _is_confirmation_reply("edit") == ("edit", "")
        assert _is_confirmation_reply("แก้ไข") == ("edit", "")

    def test_yes_with_text(self):
        result = _is_confirmation_reply("yes updated summary here")
        assert result == ("confirm", "updated summary here")

    def test_not_confirmation(self):
        assert _is_confirmation_reply("hello world") is None
        assert _is_confirmation_reply("what is this") is None
        assert _is_confirmation_reply("") is None


class TestEventToScope:
    def test_user_source(self):
        event = {"source": {"type": "user", "userId": "U123"}}
        assert event_to_scope(event) == "line-user-U123"

    def test_group_source(self):
        event = {"source": {"type": "group", "groupId": "G123"}}
        assert event_to_scope(event) == "line-group-G123"

    def test_room_source(self):
        event = {"source": {"type": "room", "roomId": "R123"}}
        assert event_to_scope(event) == "line-room-R123"

    def test_missing_source(self):
        assert event_to_scope({}) == "line-user-unknown"


class TestBuildPendingReview:
    @pytest.mark.asyncio
    async def test_text_short(self):
        from src.api.line_handler import _build_pending_review
        from src.config import Settings

        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {"type": "text", "text": "hi", "id": "1"},
            "replyToken": "rt1",
            "timestamp": 123,
        }
        settings = Settings()
        review, reason = await _build_pending_review(event, settings)
        assert review is None
        assert "สั้นเกินไป" in reason

    @pytest.mark.asyncio
    async def test_text_normal(self):
        from src.api.line_handler import _build_pending_review
        from src.config import Settings

        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {"type": "text", "text": "This is a normal message here", "id": "1"},
            "replyToken": "rt1",
            "timestamp": 123,
        }
        settings = Settings()
        review, _ = await _build_pending_review(event, settings)
        assert review is not None
        assert review["title"] == "LINE Text"
        assert review["content"] == "This is a normal message here"
        assert review["summary"] == ""  # short text, no summary
        assert review["scope"] == "line-user-U1"
        assert review["user_id"] == "U1"
        assert "line_text" in review["concepts"]

    @pytest.mark.asyncio
    async def test_text_long_gets_summary(self, monkeypatch):
        from src.api.line_handler import _build_pending_review
        from src.config import Settings

        async def mock_summarize(text, url, model="qwen2.5:7b"):
            return "Mocked summary"

        monkeypatch.setattr("src.api.line_handler._summarize_text", mock_summarize)

        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {
                "type": "text",
                "text": "This is a very long text that definitely exceeds one hundred characters in total length for sure yes indeed.",
                "id": "1",
            },
            "replyToken": "rt1",
            "timestamp": 123,
        }
        settings = Settings()
        review, _ = await _build_pending_review(event, settings)
        assert review is not None
        assert review["title"] == "LINE Text (สรุป)"
        assert review["summary"] == "Mocked summary"

    @pytest.mark.asyncio
    async def test_sticker_returns_none(self):
        from src.api.line_handler import _build_pending_review
        from src.config import Settings

        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {"type": "sticker", "id": "1"},
            "replyToken": "rt1",
            "timestamp": 123,
        }
        settings = Settings()
        review, _ = await _build_pending_review(event, settings)
        assert review is None

    @pytest.mark.asyncio
    async def test_location(self):
        from src.api.line_handler import _build_pending_review
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
        settings = Settings()
        review, _ = await _build_pending_review(event, settings)
        assert review is not None
        assert review["title"] == "LINE Location"
        assert "Bangkok" in review["content"]
        assert "13.7" in review["content"]

    @pytest.mark.asyncio
    async def test_image_no_token(self):
        from src.api.line_handler import _build_pending_review
        from src.config import Settings

        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {"type": "image", "id": "img1"},
            "replyToken": "rt1",
            "timestamp": 123,
        }
        settings = Settings()
        review, _ = await _build_pending_review(event, settings)
        assert review is not None
        assert review["title"] == "LINE Image"
        assert "no access token" in review["content"]

    @pytest.mark.asyncio
    async def test_video(self):
        from src.api.line_handler import _build_pending_review
        from src.config import Settings

        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {"type": "video", "id": "vid1"},
            "replyToken": "rt1",
            "timestamp": 123,
        }
        settings = Settings()
        review, _ = await _build_pending_review(event, settings)
        assert review is not None
        assert review["title"] == "LINE Video"

    @pytest.mark.asyncio
    async def test_audio(self):
        from src.api.line_handler import _build_pending_review
        from src.config import Settings

        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {"type": "audio", "id": "aud1"},
            "replyToken": "rt1",
            "timestamp": 123,
        }
        settings = Settings()
        review, _ = await _build_pending_review(event, settings)
        assert review is not None
        assert review["title"] == "LINE Audio"

    @pytest.mark.asyncio
    async def test_file(self):
        from src.api.line_handler import _build_pending_review
        from src.config import Settings

        event = {
            "type": "message",
            "source": {"type": "user", "userId": "U1"},
            "message": {"type": "file", "fileName": "report.pdf", "id": "f1"},
            "replyToken": "rt1",
            "timestamp": 123,
        }
        settings = Settings()
        review, _ = await _build_pending_review(event, settings)
        assert review is not None
        assert review["title"] == "LINE File"
        assert "report.pdf" in review["content"]


class TestProcessLineEvents:
    @pytest.mark.asyncio
    async def test_creates_pending_review_for_text(self, clean_pg, monkeypatch):
        from src.api.line_handler import process_line_events
        from src.config import Settings

        async def mock_send_reply(token, rt, text):
            pass

        monkeypatch.setattr("src.api.line_handler._send_reply", mock_send_reply)

        events = [
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": {"type": "text", "text": "hello from line user", "id": "1"},
                "replyToken": "rt1",
                "timestamp": 123,
            }
        ]
        settings = Settings()
        stats = await process_line_events(events, clean_pg, access_token="", settings=settings)
        assert stats["created"] == 1
        assert stats["skipped"] == 0

    @pytest.mark.asyncio
    async def test_skips_stickers(self, clean_pg):
        from src.api.line_handler import process_line_events
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
        assert stats["created"] == 0

    @pytest.mark.asyncio
    async def test_confirm_pending_review(self, clean_pg, monkeypatch):
        from src.api.line_handler import process_line_events
        from src.config import Settings

        async def mock_send_reply(token, rt, text):
            pass

        monkeypatch.setattr("src.api.line_handler._send_reply", mock_send_reply)

        # First, create a pending review manually
        review = {
            "title": "Test",
            "content": "content",
            "summary": "",
            "scope": "line-user-U1",
            "doc_type": "note",
            "source_type": "line-user",
            "source_project": "line-integration",
            "oracle_name": "line-bot",
            "tags": ["line", "user", "text"],
            "concepts": ["line", "line_text", "line_user"],
            "metadata": {},
            "reply_token": "rt-old",
            "user_id": "U1",
            "chat_id": "U1",
        }
        result = await clean_pg.create_pending_review(review)
        review_id = result["id"]

        # Then send a confirmation
        events = [
            {
                "type": "message",
                "source": {"type": "user", "userId": "U1"},
                "message": {"type": "text", "text": "ใช่", "id": "2"},
                "replyToken": "rt-new",
                "timestamp": 456,
            }
        ]
        settings = Settings()
        stats = await process_line_events(events, clean_pg, access_token="", settings=settings)
        assert stats["pushed"] == 1
        assert stats["skipped"] == 0

        # Verify the document was created
        docs = await clean_pg.list_docs(scope="line-user-U1")
        assert len(docs) >= 1

    @pytest.mark.asyncio
    async def test_cancel_pending_review(self, clean_pg, monkeypatch):
        from src.api.line_handler import process_line_events
        from src.config import Settings

        async def mock_send_reply(token, rt, text):
            pass

        monkeypatch.setattr("src.api.line_handler._send_reply", mock_send_reply)

        review = {
            "title": "Test Cancel",
            "content": "cancel me",
            "summary": "",
            "scope": "line-user-U2",
            "doc_type": "note",
            "source_type": "line-user",
            "source_project": "line-integration",
            "oracle_name": "line-bot",
            "tags": ["line"],
            "concepts": ["line"],
            "metadata": {},
            "reply_token": "rt-old",
            "user_id": "U2",
            "chat_id": "U2",
        }
        await clean_pg.create_pending_review(review)

        events = [
            {
                "type": "message",
                "source": {"type": "user", "userId": "U2"},
                "message": {"type": "text", "text": "ไม่", "id": "2"},
                "replyToken": "rt-new",
                "timestamp": 456,
            }
        ]
        settings = Settings()
        stats = await process_line_events(events, clean_pg, access_token="", settings=settings)
        assert stats["skipped"] == 1
        assert stats["pushed"] == 0

        # Verify no document was created
        docs = await clean_pg.list_docs(scope="line-user-U2")
        assert len(docs) == 0

    @pytest.mark.asyncio
    async def test_non_message_events_ignored(self, clean_pg):
        from src.api.line_handler import process_line_events
        from src.config import Settings

        events = [
            {"type": "follow", "source": {"type": "user", "userId": "U1"}},
            {"type": "join", "source": {"type": "group", "groupId": "G1"}},
        ]
        settings = Settings()
        stats = await process_line_events(events, clean_pg, access_token="", settings=settings)
        assert stats["created"] == 0
        assert stats["skipped"] == 0
