"""Integration tests — Push pipeline with dual-store write and oracle path detection."""

import pytest

from src.ingest.oracle_paths import extract_metadata
from src.ingest.push import Push


@pytest.mark.asyncio
class TestPushPipeline:
    async def test_push_text_basic(self, push, clean_pg):
        result = await push.push_text(
            title="Docker Setup", content="Use compose v2 for orchestration",
            tags=["shared"], doc_type="learning",
        )
        assert result["status"] == "indexed"
        assert "shared" in result["tags"]

    async def test_push_text_with_oracle_metadata(self, push, clean_pg):
        result = await push.push_text(
            title="Pattern Found", content="RRF fusion works well",
            tags=["emily"], doc_type="pattern",
            oracle_name="emily", brain_path="ψ/memory/learnings/pattern-001.md",
            brain_tier="extrinsic", source_project="emily-oracle",
        )
        assert result["status"] == "indexed"
        doc = await clean_pg.get(result["id"])
        assert doc["oracle_name"] == "emily"
        assert doc["brain_tier"] == "extrinsic"
        assert doc["source_project"] == "emily-oracle"

    async def test_push_text_with_concepts(self, push, clean_pg):
        result = await push.push_text(
            title="Search Patterns", content="hybrid search combines dense and keyword",
            tags=["shared"], concepts=["search", "hybrid", "fusion"],
        )
        assert result["status"] == "indexed"
        doc = await clean_pg.get(result["id"])
        assert "search" in doc["concepts"]

    async def test_push_duplicate(self, push, clean_pg):
        r1 = await push.push_text(title="Test", content="same content here", tags=["shared"])
        r2 = await push.push_text(title="Test Again", content="same content here", tags=["shared"])
        assert r1["status"] == "indexed"
        assert r2["status"] == "duplicate"
        assert r1["id"] == r2["id"]

    async def test_push_same_content_dedup(self, push, clean_pg):
        """Same content with different tags still deduplicates by content_hash."""
        r1 = await push.push_text(title="A", content="unique content", tags=["shared"])
        r2 = await push.push_text(title="B", content="unique content", tags=["emily"])
        assert r1["status"] == "indexed"
        assert r2["status"] == "duplicate"
        assert r1["id"] == r2["id"]

    async def test_push_without_embed(self, push, clean_pg):
        result = await push.push_text(
            title="FTS Only", content="this is keyword searchable",
            tags=["shared"], embed=False,
        )
        assert result["status"] == "indexed"

    async def test_push_text_source_type_default(self, push, clean_pg):
        result = await push.push_text(title="Manual", content="manual push", tags=["shared"])
        doc = await clean_pg.get(result["id"])
        assert doc["source_type"] == "manual"

    async def test_push_text_webhook_source(self, push, clean_pg):
        result = await push.push_text(
            title="Webhook", content="from external project",
            tags=["maw-js"], source_type="webhook", source_project="maw-js",
        )
        doc = await clean_pg.get(result["id"])
        assert doc["source_type"] == "webhook"
        assert doc["source_project"] == "maw-js"


class TestPushOraclePathDetection:
    def test_extract_from_learnings(self):
        meta = extract_metadata(
            "/Users/doctorboyz/Code/github.com/doctorboyz/emily-oracle/ψ/memory/learnings/pattern-001.md",
            "/Users/doctorboyz/Code/github.com/doctorboyz/emily-oracle",
        )
        assert meta["doc_type"] == "knowledge"
        assert meta["oracle_name"] == "emily"
        assert meta["metadata"]["brain_tier"] == "extrinsic"

    def test_extract_from_retrospectives(self):
        meta = extract_metadata(
            "/code/broky-oracle/ψ/memory/retrospectives/2026/05/test.md",
            "/code/broky-oracle",
        )
        assert meta["doc_type"] == "retro"
        assert meta["oracle_name"] == "broky"

    def test_extract_from_kappa_intrinsic(self):
        meta = extract_metadata(
            "/code/pm-oracle/κ/intrinsic/instinct/oracle.md",
            "/code/pm-oracle",
        )
        assert meta["doc_type"] == "instinct"
        assert meta["metadata"]["brain_tier"] == "intrinsic"

    def test_extract_from_outbox(self):
        meta = extract_metadata(
            "/code/emily-oracle/ψ/outbox/MSG-001.md",
            "/code/emily-oracle",
        )
        assert meta["doc_type"] == "handoff"


class TestSemanticDedup:
    @pytest.mark.asyncio
    async def test_semantic_duplicate_detected(self, clean_pg, monkeypatch):
        """If pgvector returns a high-similarity match, mark as semantic_duplicate."""
        from src.embed.ollama import OllamaEmbedder

        embedder = OllamaEmbedder.__new__(OllamaEmbedder)

        async def mock_embed(text):
            return [0.1] * 768

        async def mock_search_similar(vector, tags=None, limit=1, threshold=None):
            return [
                {"id": "abc-123", "title": "Similar doc", "scope": "shared", "doc_type": "learning", "score": 0.92}
            ]

        monkeypatch.setattr(embedder, "embed", mock_embed)
        monkeypatch.setattr(clean_pg, "search_similar", mock_search_similar)

        push = Push(clean_pg, embedder)
        result = await push.push_text(
            title="New doc", content="some content about Python", tags=["shared"], embed=False
        )
        assert result["status"] == "semantic_duplicate"
        assert result["similarity_score"] == 0.92

    @pytest.mark.asyncio
    async def test_semantic_dedup_no_match(self, clean_pg, monkeypatch):
        """If similarity is below threshold, proceed to store normally."""
        from src.embed.ollama import OllamaEmbedder

        embedder = OllamaEmbedder.__new__(OllamaEmbedder)

        async def mock_embed(text):
            return [0.1] * 768

        async def mock_search_similar(vector, tags=None, limit=1, threshold=None):
            return [
                {"id": "abc-123", "title": "Somewhat related", "scope": "shared", "doc_type": "learning", "score": 0.75}
            ]

        monkeypatch.setattr(embedder, "embed", mock_embed)
        monkeypatch.setattr(clean_pg, "search_similar", mock_search_similar)

        push = Push(clean_pg, embedder)
        result = await push.push_text(
            title="New doc", content="some content about Python", tags=["shared"], embed=False
        )
        assert result["status"] == "indexed"

    @pytest.mark.asyncio
    async def test_semantic_dedup_no_embedder(self, clean_pg):
        """If embedder missing, skip semantic dedup and store."""
        push = Push(clean_pg, embedder=None)
        result = await push.push_text(
            title="New doc", content="some content", tags=["shared"]
        )
        assert result["status"] == "indexed"

    @pytest.mark.asyncio
    async def test_supersede_and_reindex_basic(self, push, clean_pg):
        """Supersede creates new doc, marks old as superseded in PG."""
        add_result = await clean_pg.add(
            title="Original", content="version 1",
            source_file="/scan/file.md", source_project="test-proj",
            doc_type="note",
        )
        result = await push.supersede_and_reindex(
            old_id=add_result["id"],
            content="version 2 updated",
            title="Original",
            doc_type="note",
            source_file="/scan/file.md",
            source_project="test-proj",
            tags=["test"],
            reason="content_updated",
        )
        assert result["status"] == "superseded"
        assert result["old_id"] == add_result["id"]
        assert result["id"] != add_result["id"]

        old_doc = await clean_pg.get(add_result["id"])
        assert old_doc["superseded_by"] is not None

    @pytest.mark.asyncio
    async def test_supersede_and_reindex_inherits_concepts(self, push, clean_pg):
        """Supersede inherits concepts from old doc."""
        add_result = await clean_pg.add(
            title="Concept Test", content="original",
            source_file="/scan/concept.md", source_project="proj",
            concepts=["original-concept"],
        )
        result = await push.supersede_and_reindex(
            old_id=add_result["id"],
            content="DockerCompose is great for #container orchestration",
            title="Concept Test",
            source_file="/scan/concept.md",
            source_project="proj",
        )
        assert result["status"] == "superseded"
        new_doc = await clean_pg.get(result["id"])
        assert "original-concept" in new_doc["concepts"]  # inherited from old

    @pytest.mark.asyncio
    async def test_supersede_and_reindex_with_embedder(self, clean_pg, monkeypatch):
        """Supersede with embedder clears old embedding and embeds new doc."""
        from src.embed.ollama import OllamaEmbedder

        embedder = OllamaEmbedder.__new__(OllamaEmbedder)

        async def mock_embed(text):
            return [0.1] * 768

        clear_calls = []
        set_calls = []

        async def mock_clear_embedding(old_id):
            clear_calls.append(old_id)

        async def mock_set_embedding(doc_id, vector):
            set_calls.append(doc_id)

        monkeypatch.setattr(embedder, "embed", mock_embed)
        monkeypatch.setattr(clean_pg, "clear_embedding", mock_clear_embedding)
        monkeypatch.setattr(clean_pg, "set_embedding", mock_set_embedding)

        add_result = await clean_pg.add(
            title="Test", content="original content",
            source_file="/scan/test.md", source_project="proj",
        )

        push = Push(clean_pg, embedder)
        result = await push.supersede_and_reindex(
            old_id=add_result["id"],
            content="updated content",
            title="Test",
            source_file="/scan/test.md",
            source_project="proj",
        )
        assert result["status"] == "superseded"
        assert len(clear_calls) == 1
        assert clear_calls[0] == add_result["id"]
        assert len(set_calls) == 1
        assert set_calls[0] == result["id"]

    @pytest.mark.asyncio
    async def test_supersede_and_reindex_no_embedder(self, clean_pg):
        """Supersede without embedder works fine (PG-only mode)."""
        add_result = await clean_pg.add(
            title="No Embedder", content="original",
            source_file="/scan/no-embedder.md", source_project="proj",
        )
        push = Push(clean_pg, embedder=None)
        result = await push.supersede_and_reindex(
            old_id=add_result["id"],
            content="updated without embedder",
            title="No Embedder",
            source_file="/scan/no-embedder.md",
            source_project="proj",
        )
        assert result["status"] == "superseded"

    @pytest.mark.asyncio
    async def test_supersede_and_reindex_default_doc_type(self, push, clean_pg):
        """Default doc_type should be 'note'."""
        add_result = await clean_pg.add(
            title="Default Type", content="original",
            source_file="/scan/default.md", source_project="proj",
        )
        result = await push.supersede_and_reindex(
            old_id=add_result["id"],
            content="updated content",
            title="Default Type",
            source_file="/scan/default.md",
            source_project="proj",
        )
        new_doc = await clean_pg.get(result["id"])
        assert new_doc["doc_type"] == "note"  # default doc_type, inherited from old

    @pytest.mark.asyncio
    async def test_semantic_dedup_empty_results(self, clean_pg, monkeypatch):
        """If pgvector returns nothing, proceed to store."""
        from src.embed.ollama import OllamaEmbedder

        embedder = OllamaEmbedder.__new__(OllamaEmbedder)

        async def mock_embed(text):
            return [0.1] * 768

        async def mock_search_similar(vector, tags=None, limit=1, threshold=None):
            return []

        monkeypatch.setattr(embedder, "embed", mock_embed)
        monkeypatch.setattr(clean_pg, "search_similar", mock_search_similar)

        push = Push(clean_pg, embedder)
        result = await push.push_text(
            title="New doc", content="some content", tags=["shared"], embed=False
        )
        assert result["status"] == "indexed"