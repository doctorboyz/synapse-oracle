"""Tests for reconcile.llm — analyze_conflict and summarize_content."""

import pytest

from src.reconcile.llm import analyze_conflict, summarize_content


class MockResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json


class MockAsyncClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, *args, **kwargs):
        return self._response


class MockSettings:
    ollama_url = "http://localhost:11434"


def _patch_httpx(monkeypatch, response):
    monkeypatch.setattr(
        "src.reconcile.llm.httpx.AsyncClient",
        lambda *args, **kwargs: MockAsyncClient(response),
    )


class TestAnalyzeConflict:
    @pytest.mark.asyncio
    async def test_analyze_conflict_success_plain_json(self, monkeypatch):
        response = MockResponse(
            status_code=200,
            json_data={
                "response": (
                    '{"is_conflict": true, "conflict_type": "contradiction", '
                    '"reason": "A contradicts B", "supersede_id": "a", "merged_content": "merged"}'
                )
            },
        )
        _patch_httpx(monkeypatch, response)
        result = await analyze_conflict(
            doc_a={"title": "A", "content": "content a"},
            doc_b={"title": "B", "content": "content b"},
            settings=MockSettings(),
        )
        assert result["is_conflict"] is True
        assert result["conflict_type"] == "contradiction"
        assert result["reason"] == "A contradicts B"
        assert result["supersede_id"] == "a"
        assert result["merged_content"] == "merged"

    @pytest.mark.asyncio
    async def test_analyze_conflict_success_markdown_json_block(self, monkeypatch):
        response = MockResponse(
            status_code=200,
            json_data={
                "response": (
                    '```json\n'
                    '{"is_conflict": false, "conflict_type": "none", '
                    '"reason": "no conflict", "supersede_id": "none", "merged_content": ""}\n'
                    '```'
                )
            },
        )
        _patch_httpx(monkeypatch, response)
        result = await analyze_conflict(
            doc_a={"title": "A", "content": "content a"},
            doc_b={"title": "B", "content": "content b"},
            settings=MockSettings(),
        )
        assert result["is_conflict"] is False
        assert result["conflict_type"] == "none"

    @pytest.mark.asyncio
    async def test_analyze_conflict_success_markdown_generic_block(self, monkeypatch):
        response = MockResponse(
            status_code=200,
            json_data={
                "response": (
                    '```\n'
                    '{"is_conflict": true, "conflict_type": "overlap", '
                    '"reason": "overlap", "supersede_id": "b", "merged_content": "merged"}\n'
                    '```'
                )
            },
        )
        _patch_httpx(monkeypatch, response)
        result = await analyze_conflict(
            doc_a={"title": "A", "content": "content a"},
            doc_b={"title": "B", "content": "content b"},
            settings=MockSettings(),
        )
        assert result["is_conflict"] is True
        assert result["conflict_type"] == "overlap"

    @pytest.mark.asyncio
    async def test_analyze_conflict_normalizes_string_true(self, monkeypatch):
        response = MockResponse(
            status_code=200,
            json_data={
                "response": (
                    '{"is_conflict": "true", "conflict_type": "contradiction", '
                    '"reason": "r", "supersede_id": "a", "merged_content": ""}'
                )
            },
        )
        _patch_httpx(monkeypatch, response)
        result = await analyze_conflict(
            doc_a={"title": "A", "content": "a"},
            doc_b={"title": "B", "content": "b"},
            settings=MockSettings(),
        )
        assert result["is_conflict"] is True

    @pytest.mark.asyncio
    async def test_analyze_conflict_normalizes_string_yes(self, monkeypatch):
        response = MockResponse(
            status_code=200,
            json_data={
                "response": (
                    '{"is_conflict": "yes", "conflict_type": "contradiction", '
                    '"reason": "r", "supersede_id": "a", "merged_content": ""}'
                )
            },
        )
        _patch_httpx(monkeypatch, response)
        result = await analyze_conflict(
            doc_a={"title": "A", "content": "a"},
            doc_b={"title": "B", "content": "b"},
            settings=MockSettings(),
        )
        assert result["is_conflict"] is True

    @pytest.mark.asyncio
    async def test_analyze_conflict_normalizes_string_false(self, monkeypatch):
        response = MockResponse(
            status_code=200,
            json_data={
                "response": (
                    '{"is_conflict": "false", "conflict_type": "none", '
                    '"reason": "r", "supersede_id": "none", "merged_content": ""}'
                )
            },
        )
        _patch_httpx(monkeypatch, response)
        result = await analyze_conflict(
            doc_a={"title": "A", "content": "a"},
            doc_b={"title": "B", "content": "b"},
            settings=MockSettings(),
        )
        assert result["is_conflict"] is False

    @pytest.mark.asyncio
    async def test_analyze_conflict_http_error(self, monkeypatch):
        response = MockResponse(status_code=500, json_data={})
        _patch_httpx(monkeypatch, response)
        result = await analyze_conflict(
            doc_a={"title": "A", "content": "a"},
            doc_b={"title": "B", "content": "b"},
            settings=MockSettings(),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_conflict_json_decode_error(self, monkeypatch):
        response = MockResponse(
            status_code=200,
            json_data={"response": "not valid json"},
        )
        _patch_httpx(monkeypatch, response)
        result = await analyze_conflict(
            doc_a={"title": "A", "content": "a"},
            doc_b={"title": "B", "content": "b"},
            settings=MockSettings(),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_conflict_exception(self, monkeypatch):
        class BrokenClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, *args, **kwargs):
                raise RuntimeError("connection failed")

        monkeypatch.setattr(
            "src.reconcile.llm.httpx.AsyncClient",
            lambda *args, **kwargs: BrokenClient(),
        )
        result = await analyze_conflict(
            doc_a={"title": "A", "content": "a"},
            doc_b={"title": "B", "content": "b"},
            settings=MockSettings(),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_conflict_falls_back_when_primary_missing(self, monkeypatch):
        """Primary judge model missing (404) -> fallback model answers."""
        from src.reconcile.llm import JUDGE_MODEL_CHAIN

        # Only the LAST model in the chain is "installed"; everything else 404s
        known_models = {JUDGE_MODEL_CHAIN[-1]}
        requested = []

        class ModelAwareClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, url, json=None):
                requested_model = (json or {}).get("model")
                requested.append(requested_model)
                if requested_model not in known_models:
                    return MockResponse(
                        status_code=404,
                        json_data={"error": f"model '{requested_model}' not found"},
                    )
                return MockResponse(
                    status_code=200,
                    json_data={
                        "response": (
                            '{"is_conflict": false, "conflict_type": "none", '
                            '"reason": "r", "supersede_id": "none", "merged_content": ""}'
                        )
                    },
                )

        monkeypatch.setattr(
            "src.reconcile.llm.httpx.AsyncClient",
            lambda *args, **kwargs: ModelAwareClient(),
        )
        result = await analyze_conflict(
            doc_a={"title": "A", "content": "a"},
            doc_b={"title": "B", "content": "b"},
            settings=MockSettings(),
        )
        assert result is not None
        assert result["is_conflict"] is False
        assert requested == JUDGE_MODEL_CHAIN  # primary tried first, fallback saved us

    @pytest.mark.asyncio
    async def test_analyze_conflict_all_models_fail_returns_none(self, monkeypatch):
        """Every judge model 404s -> must return None (caller reports llm_errors)."""
        class AlwaysMissingClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, url, json=None):
                requested_model = (json or {}).get("model")
                return MockResponse(
                    status_code=404,
                    json_data={"error": f"model '{requested_model}' not found"},
                )

        monkeypatch.setattr(
            "src.reconcile.llm.httpx.AsyncClient",
            lambda *args, **kwargs: AlwaysMissingClient(),
        )
        result = await analyze_conflict(
            doc_a={"title": "A", "content": "a"},
            doc_b={"title": "B", "content": "b"},
            settings=MockSettings(),
        )
        assert result is None


class TestSummarizeContent:
    @pytest.mark.asyncio
    async def test_summarize_content_success(self, monkeypatch):
        response = MockResponse(
            status_code=200,
            json_data={"response": "This is a summary."},
        )
        _patch_httpx(monkeypatch, response)
        result = await summarize_content(
            content="Long content here.",
            title="Title",
            settings=MockSettings(),
        )
        assert result == "This is a summary."

    @pytest.mark.asyncio
    async def test_summarize_content_non_200(self, monkeypatch):
        response = MockResponse(status_code=500, json_data={})
        _patch_httpx(monkeypatch, response)
        result = await summarize_content(
            content="Long content here.",
            title="Title",
            settings=MockSettings(),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_summarize_content_exception(self, monkeypatch):
        class BrokenClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def post(self, *args, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr(
            "src.reconcile.llm.httpx.AsyncClient",
            lambda *args, **kwargs: BrokenClient(),
        )
        result = await summarize_content(
            content="Long content here.",
            title="Title",
            settings=MockSettings(),
        )
        assert result is None
