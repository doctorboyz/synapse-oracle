"""Tests for reconcile.defrag — duplicate compaction."""

import pytest
from unittest.mock import AsyncMock

from src.reconcile.defrag import defrag


class MockPgStore:
    def __init__(self, list_docs_return=None, get_map=None, supersede_return=None):
        self.list_docs = AsyncMock(return_value=list_docs_return or [])
        self._get_map = get_map or {}
        # defrag routes supersedes through the push pipeline, which calls
        # the raw primitive (_supersede_raw) — mirror both.
        self._supersede_raw = AsyncMock(return_value=supersede_return or {"id": "new-id"})
        # defrag phase 1 reads hashes in one bulk query — mirror get_map so
        # tests keep describing docs via the same fixture shape.
        self.list_doc_hashes = AsyncMock(return_value=[
            {
                "id": d["id"],
                "title": d.get("title", ""),
                "tags": d.get("tags", []),
                "content_hash": d.get("content_hash"),
            }
            for d in self._get_map.values()
        ])

    async def get(self, doc_id, include_chain=False):
        return self._get_map.get(doc_id)


class TestDefrag:
    @pytest.mark.asyncio
    async def test_defrag_empty_docs(self):
        pg = MockPgStore(list_docs_return=[])
        result = await defrag(pg)
        assert result["duplicates_found"] == 0
        assert result["compacted"] == 0
        assert result["errors"] == 0
        assert result["groups"] == []
        pg.list_docs.assert_awaited_once_with(scope=None, tags=None, limit=10000, order="newest")

    @pytest.mark.asyncio
    async def test_defrag_no_duplicates(self):
        pg = MockPgStore(
            list_docs_return=[{"id": "d1"}, {"id": "d2"}],
            get_map={
                "d1": {"id": "d1", "title": "Title A", "tags": ["s1"], "content": "a", "content_hash": "hash-a"},
                "d2": {"id": "d2", "title": "Title B", "tags": ["s1"], "content": "b", "content_hash": "hash-b"},
            },
        )
        result = await defrag(pg)
        assert result["duplicates_found"] == 0
        assert result["compacted"] == 0
        assert result["errors"] == 0
        assert result["groups"] == []

    @pytest.mark.asyncio
    async def test_defrag_finds_duplicates_and_supersedes(self):
        pg = MockPgStore(
            list_docs_return=[{"id": "d1"}, {"id": "d2"}, {"id": "d3"}],
            get_map={
                "d1": {"id": "d1", "title": "Same Title", "tags": ["s1"], "content": "a", "content_hash": "same"},
                "d2": {"id": "d2", "title": "Same Title", "tags": ["s1"], "content": "b", "content_hash": "same"},
                "d3": {"id": "d3", "title": "Other Title", "tags": ["s1"], "content": "c", "content_hash": "other"},
            },
        )
        result = await defrag(pg)
        assert result["duplicates_found"] == 1
        assert result["compacted"] == 1
        assert result["errors"] == 0
        assert len(result["groups"]) == 1
        group = result["groups"][0]
        assert group["title"] == "Same Title"
        assert group["tags"] == ["s1"]
        assert group["count"] == 2
        assert group["keep"] == "d1"
        assert group["supersede"] == ["d2"]
        assert group["action"] == "superseded"
        pg._supersede_raw.assert_awaited_once_with(
            old_id="d2", new_content="b", reason="defrag_exact_duplicate",
            new_title=None,
        )

    @pytest.mark.asyncio
    async def test_defrag_dry_run(self):
        pg = MockPgStore(
            list_docs_return=[{"id": "d1"}, {"id": "d2"}],
            get_map={
                "d1": {"id": "d1", "title": "Same Title", "tags": ["s1"], "content": "a", "content_hash": "same"},
                "d2": {"id": "d2", "title": "Same Title", "tags": ["s1"], "content": "b", "content_hash": "same"},
            },
        )
        result = await defrag(pg, dry_run=True)
        assert result["duplicates_found"] == 1
        assert result["compacted"] == 1
        assert result["errors"] == 0
        assert result["groups"][0]["action"] == "would_supersede"
        pg._supersede_raw.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_defrag_scope_filter(self):
        pg = MockPgStore(list_docs_return=[])
        result = await defrag(pg, scope="my-scope")
        pg.list_docs.assert_awaited_once_with(scope="my-scope", tags=None, limit=10000, order="newest")

    @pytest.mark.asyncio
    async def test_defrag_supersede_error(self):
        pg = MockPgStore(
            list_docs_return=[{"id": "d1"}, {"id": "d2"}],
            get_map={
                "d1": {"id": "d1", "title": "Same Title", "tags": ["s1"], "content": "a", "content_hash": "same"},
                "d2": {"id": "d2", "title": "Same Title", "tags": ["s1"], "content": "b", "content_hash": "same"},
            },
        )
        pg._supersede_raw.side_effect = RuntimeError("db locked")
        result = await defrag(pg)
        assert result["duplicates_found"] == 1
        assert result["compacted"] == 0
        assert result["errors"] == 1

    @pytest.mark.asyncio
    async def test_defrag_missing_full_doc(self):
        pg = MockPgStore(
            list_docs_return=[{"id": "d1"}, {"id": "d2"}],
            get_map={
                "d1": {"id": "d1", "title": "Same Title", "tags": ["s1"], "content": "a", "content_hash": "same"},
            },
        )
        result = await defrag(pg)
        assert result["duplicates_found"] == 0
        assert result["compacted"] == 0
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_defrag_multiple_groups(self):
        pg = MockPgStore(
            list_docs_return=[
                {"id": "d1"},
                {"id": "d2"},
                {"id": "d3"},
                {"id": "d4"},
            ],
            get_map={
                "d1": {"id": "d1", "title": "Title A", "tags": ["s1"], "content": "a", "content_hash": "hash-a"},
                "d2": {"id": "d2", "title": "Title A", "tags": ["s1"], "content": "b", "content_hash": "hash-a"},
                "d3": {"id": "d3", "title": "Title B", "tags": ["s2"], "content": "c", "content_hash": "hash-b"},
                "d4": {"id": "d4", "title": "Title B", "tags": ["s2"], "content": "d", "content_hash": "hash-b"},
            },
        )
        result = await defrag(pg)
        assert result["duplicates_found"] == 2
        assert result["compacted"] == 2
        assert result["errors"] == 0
        assert len(result["groups"]) == 2
        titles = {g["title"] for g in result["groups"]}
        assert titles == {"Title A", "Title B"}
