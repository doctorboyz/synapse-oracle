"""Tests for reconcile.detox — conflict detection and resolution."""

import sys

import pytest
from unittest.mock import AsyncMock

from src.reconcile.detox import detox

# Import the actual module object (not the function shadowed by __init__.py)
detox_module = sys.modules["src.reconcile.detox"]


class MockPgStore:
    def __init__(self, list_docs_return=None, get_map=None, supersede_return=None):
        self.list_docs = AsyncMock(return_value=list_docs_return or [])
        self._get_map = get_map or {}
        self._list_docs = list_docs_return or []
        self.supersede = AsyncMock(return_value=supersede_return or {"id": "resolved-id"})

    async def get(self, doc_id, include_chain=False):
        return self._get_map.get(doc_id)

    async def search_similar(self, vector, tags=None, limit=10, threshold=None):
        """Return other docs from list_docs as mock ANN candidates."""
        results = []
        for doc in self._list_docs:
            results.append({
                "id": doc["id"],
                "title": doc.get("title", ""),
                "scope": doc.get("scope", ""),
                "doc_type": doc.get("doc_type", ""),
                "score": 0.85,
            })
        return results


class MockSettings:
    ollama_url = "http://localhost:11434"


class MockEmbedder:
    def __init__(self):
        self.embed = AsyncMock(return_value=[0.1] * 768)


def _make_analysis(is_conflict, merged_content=None, supersede_id="a", reason="conflict"):
    return {
        "is_conflict": is_conflict,
        "conflict_type": "contradiction" if is_conflict else "none",
        "reason": reason,
        "supersede_id": supersede_id,
        "merged_content": merged_content or "",
    }


class TestDetox:
    @pytest.mark.asyncio
    async def test_detox_empty_docs(self):
        pg = MockPgStore(list_docs_return=[])
        result = await detox(pg, embedder=MockEmbedder(), settings=MockSettings())
        assert result["conflicts_found"] == 0
        assert result["conflicts"] == []
        assert result["resolutions"] == []
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_detox_single_doc(self):
        pg = MockPgStore(
            list_docs_return=[
                {"id": "d1", "title": "Only", "scope": "s1", "doc_type": "learning"}
            ]
        )
        result = await detox(pg, embedder=MockEmbedder(), settings=MockSettings())
        assert result["conflicts_found"] == 0

    @pytest.mark.asyncio
    async def test_detox_no_pairs_different_scope(self, monkeypatch):
        pg = MockPgStore(
            list_docs_return=[
                {"id": "d1", "title": "A", "scope": "s1", "doc_type": "learning"},
                {"id": "d2", "title": "B", "scope": "s2", "doc_type": "learning"},
            ]
        )
        # Fallback mode pairs all docs regardless of scope — mock the judge
        # so the test stays hermetic (no live Ollama dependency)
        monkeypatch.setattr(
            detox_module,
            "analyze_conflict",
            AsyncMock(return_value=_make_analysis(False)),
        )
        result = await detox(pg, embedder=None, settings=MockSettings())
        assert result["pairs_analyzed"] == 1
        assert result["conflicts_found"] == 0
        assert result["llm_errors"] == 0

    @pytest.mark.asyncio
    async def test_detox_no_pairs_different_type(self):
        pg = MockPgStore(
            list_docs_return=[
                {"id": "d1", "title": "A", "scope": "s1", "doc_type": "learning"},
                {"id": "d2", "title": "B", "scope": "s1", "doc_type": "pattern"},
            ]
        )
        result = await detox(pg, embedder=MockEmbedder(), settings=MockSettings())
        assert result["conflicts_found"] == 0

    @pytest.mark.asyncio
    async def test_detox_conflict_detected_and_resolved(self, monkeypatch):
        pg = MockPgStore(
            list_docs_return=[
                {"id": "d1", "title": "A", "scope": "s1", "doc_type": "learning"},
                {"id": "d2", "title": "B", "scope": "s1", "doc_type": "learning"},
            ],
            get_map={
                "d1": {"id": "d1", "title": "A", "scope": "s1", "content": "content a"},
                "d2": {"id": "d2", "title": "B", "scope": "s1", "content": "content b"},
            },
        )
        monkeypatch.setattr(
            detox_module,
            "analyze_conflict",
            AsyncMock(
                return_value=_make_analysis(
                    True, merged_content="merged", supersede_id="a", reason="contradiction"
                )
            ),
        )
        result = await detox(pg, embedder=MockEmbedder(), settings=MockSettings())
        assert result["conflicts_found"] == 1
        assert result["errors"] == 0
        assert len(result["resolutions"]) == 1
        resolution = result["resolutions"][0]
        assert resolution["old_id"] == "d1"
        assert resolution["reason"] == "contradiction"
        pg.supersede.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_detox_resolves_with_supersede_id_b(self, monkeypatch):
        pg = MockPgStore(
            list_docs_return=[
                {"id": "d1", "title": "A", "scope": "s1", "doc_type": "learning"},
                {"id": "d2", "title": "B", "scope": "s1", "doc_type": "learning"},
            ],
            get_map={
                "d1": {"id": "d1", "title": "A", "scope": "s1", "content": "a"},
                "d2": {"id": "d2", "title": "B", "scope": "s1", "content": "b"},
            },
        )
        monkeypatch.setattr(
            detox_module,
            "analyze_conflict",
            AsyncMock(
                return_value=_make_analysis(True, merged_content="merged", supersede_id="b")
            ),
        )
        result = await detox(pg, embedder=MockEmbedder(), settings=MockSettings())
        assert result["conflicts_found"] == 1
        assert len(result["resolutions"]) == 1
        assert result["resolutions"][0]["old_id"] == "d2"

    @pytest.mark.asyncio
    async def test_detox_dry_run(self, monkeypatch):
        pg = MockPgStore(
            list_docs_return=[
                {"id": "d1", "title": "A", "scope": "s1", "doc_type": "learning"},
                {"id": "d2", "title": "B", "scope": "s1", "doc_type": "learning"},
            ],
            get_map={
                "d1": {"id": "d1", "title": "A", "scope": "s1", "content": "a"},
                "d2": {"id": "d2", "title": "B", "scope": "s1", "content": "b"},
            },
        )
        monkeypatch.setattr(
            detox_module,
            "analyze_conflict",
            AsyncMock(
                return_value=_make_analysis(True, merged_content="merged", supersede_id="a")
            ),
        )
        result = await detox(pg, embedder=MockEmbedder(), settings=MockSettings(), dry_run=True)
        assert result["conflicts_found"] == 1
        assert len(result["resolutions"]) == 0
        pg.supersede.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_detox_no_embedder(self, monkeypatch):
        pg = MockPgStore(
            list_docs_return=[
                {"id": "d1", "title": "A", "scope": "s1", "doc_type": "learning"},
                {"id": "d2", "title": "B", "scope": "s1", "doc_type": "learning"},
            ],
            get_map={
                "d1": {"id": "d1", "title": "A", "scope": "s1", "content": "a"},
                "d2": {"id": "d2", "title": "B", "scope": "s1", "content": "b"},
            },
        )
        # embedder=None -> fallback pairwise path still analyzes pairs.
        # Mock the judge so the test stays hermetic (no live Ollama dependency).
        monkeypatch.setattr(
            detox_module,
            "analyze_conflict",
            AsyncMock(
                return_value=_make_analysis(True, merged_content="merged", supersede_id="a")
            ),
        )
        result = await detox(pg, embedder=None, settings=MockSettings())
        assert result["conflicts_found"] == 1
        assert result["conflicts_resolved"] == 1
        assert result["llm_errors"] == 0
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_detox_no_settings(self):
        pg = MockPgStore(
            list_docs_return=[
                {"id": "d1", "title": "A", "scope": "s1", "doc_type": "learning"},
                {"id": "d2", "title": "B", "scope": "s1", "doc_type": "learning"},
            ]
        )
        result = await detox(pg, embedder=None, settings=None)
        # settings=None -> pairs skipped before analysis; judge not consulted
        assert result["llm_errors"] == 0
        assert result["errors"] == 0
        assert result["conflicts_found"] == 0

    @pytest.mark.asyncio
    async def test_detox_missing_full_doc(self, monkeypatch):
        pg = MockPgStore(
            list_docs_return=[
                {"id": "d1", "title": "A", "scope": "s1", "doc_type": "learning"},
                {"id": "d2", "title": "B", "scope": "s1", "doc_type": "learning"},
            ],
            get_map={
                "d1": {"id": "d1", "title": "A", "scope": "s1", "content": "a"},
            },
        )
        monkeypatch.setattr(
            detox_module,
            "analyze_conflict",
            AsyncMock(return_value=_make_analysis(True)),
        )
        # Fallback mode: uses list_docs data when full doc missing → still finds conflicts
        result = await detox(pg, embedder=None, settings=MockSettings())
        assert result["conflicts_found"] == 1
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_detox_analyze_conflict_returns_none(self, monkeypatch):
        pg = MockPgStore(
            list_docs_return=[
                {"id": "d1", "title": "A", "scope": "s1", "doc_type": "learning"},
                {"id": "d2", "title": "B", "scope": "s1", "doc_type": "learning"},
            ],
            get_map={
                "d1": {"id": "d1", "title": "A", "scope": "s1", "content": "a"},
                "d2": {"id": "d2", "title": "B", "scope": "s1", "content": "b"},
            },
        )
        monkeypatch.setattr(
            detox_module,
            "analyze_conflict",
            AsyncMock(return_value=None),
        )
        result = await detox(pg, embedder=None, settings=MockSettings())
        # Judge returned None (all models failed) -> llm_errors, NOT a silent zero
        assert result["llm_errors"] == 1
        assert result["conflicts_found"] == 0
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_detox_analyze_conflict_no_conflict(self, monkeypatch):
        pg = MockPgStore(
            list_docs_return=[
                {"id": "d1", "title": "A", "scope": "s1", "doc_type": "learning"},
                {"id": "d2", "title": "B", "scope": "s1", "doc_type": "learning"},
            ],
            get_map={
                "d1": {"id": "d1", "title": "A", "scope": "s1", "content": "a"},
                "d2": {"id": "d2", "title": "B", "scope": "s1", "content": "b"},
            },
        )
        monkeypatch.setattr(
            detox_module,
            "analyze_conflict",
            AsyncMock(return_value=_make_analysis(False)),
        )
        result = await detox(pg, embedder=MockEmbedder(), settings=MockSettings())
        assert result["conflicts_found"] == 0
        assert result["errors"] == 0
        assert len(result["conflicts"]) == 0

    @pytest.mark.asyncio
    async def test_detox_supersede_error(self, monkeypatch):
        pg = MockPgStore(
            list_docs_return=[
                {"id": "d1", "title": "A", "scope": "s1", "doc_type": "learning"},
                {"id": "d2", "title": "B", "scope": "s1", "doc_type": "learning"},
            ],
            get_map={
                "d1": {"id": "d1", "title": "A", "scope": "s1", "content": "a"},
                "d2": {"id": "d2", "title": "B", "scope": "s1", "content": "b"},
            },
        )
        pg.supersede.side_effect = RuntimeError("db locked")
        monkeypatch.setattr(
            detox_module,
            "analyze_conflict",
            AsyncMock(
                return_value=_make_analysis(True, merged_content="merged", supersede_id="a")
            ),
        )
        result = await detox(pg, embedder=MockEmbedder(), settings=MockSettings())
        assert result["conflicts_found"] == 1
        assert result["errors"] == 1
        assert len(result["resolutions"]) == 0

    @pytest.mark.asyncio
    async def test_detox_multiple_pairs(self, monkeypatch):
        pg = MockPgStore(
            list_docs_return=[
                {"id": "d1", "title": "A", "scope": "s1", "doc_type": "learning"},
                {"id": "d2", "title": "B", "scope": "s1", "doc_type": "learning"},
                {"id": "d3", "title": "C", "scope": "s1", "doc_type": "learning"},
            ],
            get_map={
                "d1": {"id": "d1", "title": "A", "scope": "s1", "content": "a"},
                "d2": {"id": "d2", "title": "B", "scope": "s1", "content": "b"},
                "d3": {"id": "d3", "title": "C", "scope": "s1", "content": "c"},
            },
        )
        call_count = 0

        async def mock_analyze(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _make_analysis(True, merged_content="merged", supersede_id="a")

        monkeypatch.setattr(detox_module, "analyze_conflict", mock_analyze)
        result = await detox(pg, embedder=MockEmbedder(), settings=MockSettings())
        assert call_count == 3
        assert result["conflicts_found"] == 3
        assert result["errors"] == 0
        assert len(result["resolutions"]) == 3

    @pytest.mark.asyncio
    async def test_detox_scope_filter(self):
        pg = MockPgStore(list_docs_return=[])
        result = await detox(pg, embedder=MockEmbedder(), settings=MockSettings(), scope="my-scope")
        pg.list_docs.assert_awaited_once_with(scope="my-scope", tags=None, limit=10000, order="newest")
