"""Tests for MCP server tool handlers."""

import json
import pytest

from src.mcp.server import create_app


class TestMCPSearch:
    @pytest.mark.asyncio
    async def test_search_fts_mode(self, app_components):
        pg, push, search = app_components
        await push.push_text(title="Python Patterns", content="list comprehensions and generators", tags=["shared"])
        results = await search.search("python", mode="fts")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_search_with_scope(self, app_components):
        pg, push, search = app_components
        await push.push_text(title="Shared", content="public knowledge", tags=["shared"])
        await push.push_text(title="Emily", content="private knowledge", tags=["emily"], oracle_name="emily")
        results = await search.search("knowledge", oracle="emily", mode="fts")
        assert len(results) >= 1
        assert all(r["oracle_name"] == "emily" for r in results)

    @pytest.mark.asyncio
    async def test_search_with_doc_type(self, app_components):
        pg, push, search = app_components
        await push.push_text(title="Tip", content="use venv", tags=["shared"], doc_type="learning")
        await push.push_text(title="Pattern", content="factory pattern", tags=["shared"], doc_type="pattern")
        results = await search.search("pattern", doc_type="pattern", mode="fts")
        assert len(results) >= 1
        assert all(r["doc_type"] == "pattern" for r in results)

    @pytest.mark.asyncio
    async def test_search_no_results(self, app_components):
        pg, push, search = app_components
        results = await search.search("xyznonexistent123", mode="fts")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_hybrid_fallback_fts(self, app_components):
        pg, push, search = app_components
        await push.push_text(title="Docker Tips", content="Use compose v2", tags=["shared"])
        results = await search.search("docker", mode="hybrid")
        assert len(results) >= 1


class TestMCPPush:
    @pytest.mark.asyncio
    async def test_push_and_get(self, app_components):
        pg, push, search = app_components
        result = await push.push_text(
            title="Test Doc", content="hello world", tags=["shared"], doc_type="learning",
        )
        assert result["status"] == "indexed"

        doc = await pg.get(result["id"])
        assert doc["title"] == "Test Doc"
        assert doc["content"] == "hello world"
        assert doc["doc_type"] == "learning"

    @pytest.mark.asyncio
    async def test_push_supersede_and_get_chain(self, app_components):
        pg, push, search = app_components
        add_result = await push.push_text(title="Original", content="version 1", tags=["shared"])
        supersede_result = await pg._supersede_raw(add_result["id"], "version 2")

        doc = await pg.get(add_result["id"], include_chain=True)
        assert doc["superseded_by"] is not None

    @pytest.mark.asyncio
    async def test_push_with_concepts(self, app_components):
        pg, push, search = app_components
        result = await push.push_text(
            title="Hybrid Search", content="combines dense and keyword",
            tags=["shared"], concepts=["search", "hybrid"],
        )
        concepts = await pg.list_concepts()
        names = [c["name"] for c in concepts]
        assert "search" in names


class TestMCPTrace:
    @pytest.mark.asyncio
    async def test_add_trace(self, app_components):
        pg, push, search = app_components
        doc_a = await push.push_text(title="Source", content="original", tags=["shared"])
        doc_b = await push.push_text(title="Derived", content="derived from source", tags=["shared"])
        result = await pg.add_trace(doc_a["id"], doc_b["id"], "derived_from")
        assert result["relation"] == "derived_from"

    @pytest.mark.asyncio
    async def test_trace_chain(self, app_components):
        pg, push, search = app_components
        doc_a = await push.push_text(title="A", content="original", tags=["shared"])
        doc_b = await push.push_text(title="B", content="refined", tags=["shared"])
        await pg.add_trace(doc_a["id"], doc_b["id"], "refines")
        chain = await pg.get_trace_chain(doc_a["id"], direction="downstream")
        assert len(chain) >= 1


class TestMCPScopeStats:
    @pytest.mark.asyncio
    async def test_scopes(self, app_components):
        pg, push, search = app_components
        # list_scopes reads from scope_registry — populated by register_project
        await pg.add_search_topic("emily", "test", "web", "daily")
        scopes = await pg.list_scopes()
        assert isinstance(scopes, list)

    @pytest.mark.asyncio
    async def test_stats(self, app_components):
        pg, push, search = app_components
        await push.push_text(title="A", content="test a", tags=["shared"], doc_type="learning")
        stats = await pg.stats()
        assert stats["total_documents"] >= 1

    @pytest.mark.asyncio
    async def test_list_docs(self, app_components):
        pg, push, search = app_components
        await push.push_text(title="First", content="content 1", tags=["shared"])
        await push.push_text(title="Second", content="content 2", tags=["shared"])
        docs = await pg.list_docs(limit=10)
        assert len(docs) >= 2