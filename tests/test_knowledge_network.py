"""Knowledge-network causal tests — 'stored must be findable' (audit 11/10/26).

Principle: everything pushed into the vault must be findable via fts, dense,
and hybrid — at doc or chunk level. No knowledge may be stored and then
silently unfindable.

Covers (audit item → test):
1  supersede via push pipeline must re-embed the new doc (dense must find it)
1  supersede_and_reindex must support new_title (MCP contract)
2  long docs (>4000 chars) must be findable via chunk-level dense search
5  HybridSearch must use the cache; Push must invalidate it on write
5  cache key must include all filters (doc_type/oracle/concepts) — no collisions
3  concepts filter must actually filter (fts + dense)
3  trace relation filter must be parameterized (no SQL injection)
3  synapse_fix_doctype must be a registered tool (no ghost handlers)
7  MCP tool errors must name the tool and the offending parameter

Isolation: runs on the throwaway test DB via conftest TEST_DB_URL
(synapse_test) — never the production vault.
"""

import pytest

from src.cache import SearchCache
from src.ingest.push import Push, CHUNK_SIZE
from src.mcp.server import TOOL_DEFINITIONS
from src.retrieve.hybrid_search import HybridSearch

try:
    from src.mcp.server import _format_tool_error
except ImportError:  # not implemented yet — error-context tests stay RED
    _format_tool_error = None

try:
    from src.mcp.server import _validate_tool_input
except ImportError:
    _validate_tool_input = None

VOCAB = ["flamingo", "superseded", "fresh", "docker", "redis",
         "alpha", "beta", "quantum", "extends"]


class FakeEmbedder:
    """Deterministic keyword→vector embedder for causal dense-search tests.

    Mimics the real truncation contract: callers pass pre-truncated text
    (Push truncates doc-level embeds at MAX_CHUNK_CHARS), so keywords beyond
    the truncation point are invisible at doc level but visible in chunks.
    """

    settings = None

    async def embed(self, text: str) -> list[float]:
        text = text.lower()
        vec = [1.0] + [1.0 if w in text else 0.0 for w in VOCAB]
        vec.extend([0.0] * (768 - len(vec)))  # pgvector column is vector(768)
        return vec

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]

    async def check(self) -> bool:
        return True


# ── 1. เก็บได้: supersede must re-embed ─────────────────────────────────


class TestSupersedeReindex:
    @pytest.mark.asyncio
    async def test_supersede_new_doc_findable_via_dense(self, clean_pg):
        push = Push(clean_pg, FakeEmbedder())
        old = await push.push_text(
            title="Deploy Guide", content="docker compose setup",
            tags=["test"], skip_semantic_dedup=True,
        )

        result = await push.supersede_and_reindex(
            old_id=old["id"],
            content="redis cluster failover procedure",
            title="Deploy Guide",
            reason="updated",
        )
        new_id = result["id"]
        assert new_id != old["id"]

        # Old embedding cleared, new embedding present
        async with clean_pg.pool.acquire() as conn:
            old_emb = await conn.fetchval(
                "SELECT embedding IS NULL FROM knowledge_documents WHERE id = $1",
                old["id"],
            )
            new_emb = await conn.fetchval(
                "SELECT embedding IS NOT NULL FROM knowledge_documents WHERE id = $1",
                new_id,
            )
        assert old_emb, "old doc embedding must be cleared"
        assert new_emb, "new doc must be embedded after supersede"

        # Dense search for the NEW content must find the NEW doc
        search = HybridSearch(clean_pg, FakeEmbedder())
        results = await search.search("redis failover", mode="dense")
        ids = [r["id"] for r in results]
        assert new_id in ids, f"dense search must find superseding doc, got {ids}"
        assert old["id"] not in ids, "superseded doc must not surface in dense"

    @pytest.mark.asyncio
    async def test_supersede_and_reindex_supports_new_title(self, clean_pg):
        push = Push(clean_pg, FakeEmbedder())
        old = await push.push_text(
            title="Old Title", content="quantum basics",
            tags=["test"], skip_semantic_dedup=True,
        )
        result = await push.supersede_and_reindex(
            old_id=old["id"],
            content="quantum advanced topics",
            title="New Title",
            reason="renamed",
        )
        doc = await clean_pg.get(result["id"])
        assert doc["title"] == "New Title", "new_title must be honored"

    @pytest.mark.asyncio
    async def test_supersede_long_doc_chunks_reindexed(self, clean_pg):
        push = Push(clean_pg, FakeEmbedder())
        old = await push.push_text(
            title="Long Doc", content="redis filler " * 400,
            tags=["test"], skip_semantic_dedup=True,
        )
        long_content = ("filler text no keywords here " * 200) + "redis chunk tail"
        result = await push.supersede_and_reindex(
            old_id=old["id"], content=long_content, title="Long Doc",
        )
        chunks = await clean_pg.get_chunks(result["id"])
        assert len(chunks) > 0, "superseded long doc must be chunked"


# ── 2. เรียกได้: chunk-level dense search ────────────────────────────────


class TestChunkSearch:
    @pytest.mark.asyncio
    async def test_long_doc_keyword_beyond_truncation_found_dense(self, clean_pg):
        """Keyword placed past MAX_CHUNK_CHARS (4000) is invisible to the
        doc-level embedding but must be found via chunk search."""
        push = Push(clean_pg, FakeEmbedder())
        # Decoy doc that matches nothing
        await push.push_text(
            title="Decoy", content="docker unrelated decoy",
            tags=["test"], skip_semantic_dedup=True,
        )
        # Long doc: filler for first ~4600 chars, flamingo only at the tail
        filler = "lorem ipsum dolor sit amet consectetur adipiscing elit "
        long_content = (filler * 100)[:4600] + " flamingo deployment config"
        assert len(long_content) > 4000
        assert "flamingo" in long_content[4000:]

        target = await push.push_text(
            title="Long Hidden Doc", content=long_content,
            tags=["test"], skip_semantic_dedup=True,
        )
        assert len(long_content) > CHUNK_SIZE, "doc must qualify for chunking"

        search = HybridSearch(clean_pg, FakeEmbedder())
        results = await search.search("flamingo", mode="dense")
        ids = [r["id"] for r in results]
        assert target["id"] in ids, (
            f"chunk-level dense search must find keyword beyond doc-embedding "
            f"truncation; got {ids}"
        )

    @pytest.mark.asyncio
    async def test_hybrid_result_carries_matched_chunk_content(self, clean_pg):
        """When a doc is found via chunk, the matched chunk content rides along."""
        push = Push(clean_pg, FakeEmbedder())
        filler = "lorem ipsum dolor sit amet consectetur adipiscing elit "
        long_content = (filler * 100)[:4600] + " flamingo deployment config"
        target = await push.push_text(
            title="Chunk Carrier Doc", content=long_content,
            tags=["test"], skip_semantic_dedup=True,
        )
        search = HybridSearch(clean_pg, FakeEmbedder())
        results = await search.search("flamingo", mode="hybrid")
        hit = next((r for r in results if r["id"] == target["id"]), None)
        assert hit is not None, "hybrid must find the long doc"
        assert "flamingo" in (hit.get("matched_chunk_content") or ""), (
            "chunk-hit docs must carry matched_chunk_content"
        )


# ── 5. เรียกได้: cache wiring + invalidation + key correctness ───────────


class TestSearchCacheWiring:
    @pytest.mark.asyncio
    async def test_second_identical_search_hits_cache(self, clean_pg):
        embedder = FakeEmbedder()
        cache = SearchCache()
        push = Push(clean_pg, embedder, cache=cache)
        search = HybridSearch(clean_pg, embedder, cache=cache)
        await push.push_text(
            title="Cache Doc", content="redis caching strategy",
            tags=["test"], skip_semantic_dedup=True,
        )

        calls = {"n": 0}
        orig_embed = embedder.embed

        async def counting_embed(text):
            calls["n"] += 1
            return await orig_embed(text)

        embedder.embed = counting_embed
        first = await search.search("redis", mode="dense")
        embed_calls_after_first = calls["n"]
        second = await search.search("redis", mode="dense")
        assert calls["n"] == embed_calls_after_first, (
            "identical search must be served from cache (no re-embed)"
        )
        assert [r["id"] for r in first] == [r["id"] for r in second]

    @pytest.mark.asyncio
    async def test_push_invalidates_cache(self, clean_pg):
        embedder = FakeEmbedder()
        cache = SearchCache()
        push = Push(clean_pg, embedder, cache=cache)
        search = HybridSearch(clean_pg, embedder, cache=cache)

        await push.push_text(
            title="Base", content="quantum baseline note",
            tags=["test"], skip_semantic_dedup=True,
        )
        results = await search.search("flamingo", mode="dense")
        assert all("flamingo" not in (r.get("title") or "").lower() for r in results)

        # New knowledge arrives AFTER the query was cached
        new_doc = await push.push_text(
            title="Flamingo Arrival", content="flamingo migration patterns",
            tags=["test"], skip_semantic_dedup=True,
        )

        results2 = await search.search("flamingo", mode="dense")
        ids = [r["id"] for r in results2]
        assert new_doc["id"] in ids, (
            "push must invalidate the search cache — new doc must be findable"
        )

    @pytest.mark.asyncio
    async def test_cache_key_includes_doc_type(self, clean_pg):
        """Same query, different doc_type → different answers (no key collision)."""
        embedder = FakeEmbedder()
        search = HybridSearch(clean_pg, embedder, cache=SearchCache())
        push = Push(clean_pg, embedder)
        await push.push_text(
            title="Learning Note", content="quantum entanglement learning",
            tags=["test"], doc_type="learning", skip_semantic_dedup=True,
        )
        await push.push_text(
            title="Pattern Note", content="quantum entanglement pattern",
            tags=["test"], doc_type="pattern", skip_semantic_dedup=True,
        )

        learn = await search.search("quantum", doc_type="learning", mode="fts")
        pat = await search.search("quantum", doc_type="pattern", mode="fts")
        assert [r["doc_type"] for r in learn] == ["learning"]
        assert [r["doc_type"] for r in pat] == ["pattern"], (
            "doc_type must be part of the cache key — cached learning results "
            "must not leak into pattern search"
        )


# ── 3. เชื่อมโยงได้: concepts filter ────────────────────────────────────


class TestConceptsFilter:
    @pytest.mark.asyncio
    async def test_concepts_filter_hybrid(self, clean_pg):
        push = Push(clean_pg, FakeEmbedder())
        doc_a = await push.push_text(
            title="Alpha Doc", content="quantum shared topic alpha",
            tags=["test"], concepts=["alpha"], skip_semantic_dedup=True,
        )
        doc_b = await push.push_text(
            title="Beta Doc", content="quantum shared topic beta",
            tags=["test"], concepts=["beta"], skip_semantic_dedup=True,
        )
        search = HybridSearch(clean_pg, FakeEmbedder())

        for mode in ("fts", "dense", "hybrid"):
            results = await search.search("quantum", concepts=["beta"], mode=mode)
            ids = {r["id"] for r in results}
            assert doc_b["id"] in ids, f"{mode}: filtered doc must be found"
            assert doc_a["id"] not in ids, (
                f"{mode}: concepts filter must exclude non-matching docs, got {ids}"
            )


# ── 3. เชื่อมโยงได้: trace relation parameterization + ghost tool ────────


class TestTraceAndGhostTool:
    @pytest.mark.asyncio
    async def test_trace_chain_relation_filter_strict(self, clean_pg):
        push = Push(clean_pg, FakeEmbedder())
        a = await push.push_text(title="A", content="source doc", tags=["test"],
                                 skip_semantic_dedup=True)
        b = await push.push_text(title="B", content="refined doc", tags=["test"],
                                 skip_semantic_dedup=True)
        c = await push.push_text(title="C", content="extended doc", tags=["test"],
                                 skip_semantic_dedup=True)
        await clean_pg.add_trace(a["id"], b["id"], "refines")
        await clean_pg.add_trace(a["id"], c["id"], "extends")

        # Sanity: exact relation works
        chain = await clean_pg.get_trace_chain(a["id"], direction="downstream",
                                               relation="refines")
        assert len(chain) == 1

        # Injection payload must NOT widen the filter
        evil = "nonexistent' OR t.relation = 'extends"
        chain = await clean_pg.get_trace_chain(a["id"], direction="downstream",
                                               relation=evil)
        assert chain == [], "relation filter must be parameterized (no injection)"

    def test_fix_doctype_is_registered_tool(self):
        names = {t.name for t in TOOL_DEFINITIONS}
        assert "synapse_fix_doctype" in names, (
            "handler exists but tool is not registered — agents cannot call it"
        )


# ── 7. เรียนได้: MCP error context ──────────────────────────────────────


class TestMCPErrorContext:
    def test_missing_param_error_names_tool_and_param(self):
        err = _format_tool_error("synapse_supersede", {"old_id": "x"},
                                 KeyError("new_content"))
        assert err["tool"] == "synapse_supersede"
        assert "new_content" in err["error"], "error must name the missing param"

    def test_generic_error_names_tool(self):
        err = _format_tool_error("synapse_search", {"query": "x"},
                                 ValueError("ambiguous column created_at"))
        assert err["tool"] == "synapse_search"
        assert "synapse_search" in err["error"], "error must name the failing tool"
        assert "ambiguous column created_at" in err["error"]

    def test_schema_validation_error_names_tool(self):
        """Schema violations must also name the tool, not just the param."""
        err = _validate_tool_input("synapse_supersede", {"old_id": "x"})
        assert err is not None
        assert err["tool"] == "synapse_supersede"
        assert "new_content" in err["error"]

    def test_schema_validation_passes_valid_args(self):
        err = _validate_tool_input("synapse_search", {"query": "anything"})
        assert err is None


# ── 6. เชื่อมโยงได้: defrag must not N+1 ─────────────────────────────────


class TestDefragNoNPlusOne:
    @pytest.mark.asyncio
    async def test_defrag_exact_dups_single_query(self, clean_pg, monkeypatch):
        from src.reconcile.defrag import defrag as run_defrag

        push = Push(clean_pg, None)
        content = "exact duplicate content for defrag " + "x" * 50
        # Push once, then plant clones via raw SQL — pg.add dedups identical
        # (content_hash, scope) pushes, so duplicates only exist in the wild
        # via concurrent writers / legacy imports.
        await push.push_text(
            title="Dup 0", content=content, tags=["test"],
            skip_semantic_dedup=True,
        )
        async with clean_pg.pool.acquire() as conn:
            for i in range(4):
                await conn.execute(
                    """INSERT INTO knowledge_documents (id, title, content, content_hash)
                       SELECT gen_random_uuid(), $1, content, content_hash
                       FROM knowledge_documents WHERE title = 'Dup 0'""",
                    f"Dup {i + 1}",
                )
        # Unique docs too, so grouping has work to do
        for i in range(3):
            await push.push_text(
                title=f"Unique {i}", content=f"unique content {i} " + "y" * 50,
                tags=["test"], skip_semantic_dedup=True,
            )

        get_calls = {"n": 0}
        orig_get = clean_pg.get

        async def counting_get(*args, **kwargs):
            get_calls["n"] += 1
            return await orig_get(*args, **kwargs)

        monkeypatch.setattr(clean_pg, "get", counting_get)

        result = await run_defrag(clean_pg, embedder=None, dry_run=True)
        assert result["duplicates_found"] >= 1
        assert get_calls["n"] == 0, (
            f"defrag must not fetch docs one-by-one (N+1); pg.get called "
            f"{get_calls['n']} times"
        )