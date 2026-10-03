"""Tests for HybridSearch — RRF fusion, FTS fallback."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from src.retrieve.hybrid_search import reciprocal_rank_fusion, HybridSearch


class TestReciprocalRankFusion:
    def test_merge_two_lists(self):
        list_a = [{"id": "1", "title": "A", "scope": "shared", "doc_type": "learning", "score": 0.9}]
        list_b = [{"id": "2", "title": "B", "scope": "shared", "doc_type": "pattern", "score": 0.8}]
        result = reciprocal_rank_fusion([list_a, list_b])
        assert len(result) == 2

    def test_merge_overlapping_ids(self):
        list_a = [{"id": "1", "title": "A", "scope": "shared", "doc_type": "learning", "score": 0.9}]
        list_b = [{"id": "1", "title": "A", "scope": "shared", "doc_type": "learning", "score": 0.7}]
        result = reciprocal_rank_fusion([list_a, list_b])
        assert len(result) == 1
        assert result[0]["id"] == "1"

    def test_empty_lists(self):
        result = reciprocal_rank_fusion([[], []])
        assert result == []

    def test_custom_weights(self):
        list_a = [{"id": "1", "title": "A", "scope": "shared", "doc_type": "learning", "score": 0.9}]
        list_b = [{"id": "2", "title": "B", "scope": "shared", "doc_type": "pattern", "score": 0.8}]
        result = reciprocal_rank_fusion([list_a, list_b], weights=[0.8, 0.2])
        assert len(result) == 2
        assert result[0]["id"] == "1"


@pytest.mark.asyncio
class TestHybridSearch:
    async def test_fts_mode(self, clean_pg):
        await clean_pg.add(title="Python Tips", content="Use list comprehensions")
        search = HybridSearch(clean_pg)
        results = await search.search("python", mode="fts")
        assert len(results) >= 1

    async def test_fts_mode_with_scope(self, clean_pg):
        await clean_pg.add(title="Shared Doc", content="public info")
        await clean_pg.add(title="Emily Doc", content="private info", tags=["emily"], oracle_name="emily")
        search = HybridSearch(clean_pg)
        results = await search.search("info", oracle="emily", mode="fts")
        assert len(results) >= 1
        assert all(r["oracle_name"] == "emily" for r in results)

    async def test_hybrid_falls_back_to_fts_without_embedder(self, clean_pg):
        await clean_pg.add(title="Docker Setup", content="Use compose v2")
        search = HybridSearch(clean_pg, embedder=None)
        results = await search.search("docker", mode="hybrid")
        assert len(results) >= 1

    async def test_dense_mode_without_embedder_raises(self, clean_pg):
        from src.retrieve.hybrid_search import SearchError
        search = HybridSearch(clean_pg)
        with pytest.raises(SearchError, match="Dense search requires"):
            await search.search("test", mode="dense")

    async def test_no_results(self, clean_pg):
        search = HybridSearch(clean_pg)
        results = await search.search("nonexistent_xyz", mode="fts")
        assert results == []