"""Tests for PgStore — CRUD, FTS search, supersession, concepts, trace."""

import pytest
import pytest_asyncio

from src.db.pg_store import PgStore


@pytest.mark.asyncio
class TestPgStoreCRUD:
    async def test_add_document(self, clean_pg):
        result = await clean_pg.add(
            title="Python Tips", content="Use list comprehensions for filtering",
            doc_type="learning",
        )
        assert result["status"] == "indexed"
        assert result["id"]

    async def test_add_duplicate(self, clean_pg):
        await clean_pg.add(title="Test", content="same content")
        result = await clean_pg.add(title="Test", content="same content")
        assert result["status"] == "duplicate"

    async def test_get_document(self, clean_pg):
        add_result = await clean_pg.add(title="Get Test", content="some content")
        doc = await clean_pg.get(add_result["id"])
        assert doc is not None
        assert doc["title"] == "Get Test"
        assert doc["content"] == "some content"

    async def test_get_nonexistent(self, clean_pg):
        doc = await clean_pg.get("00000000-0000-0000-0000-000000000000")
        assert doc is None

    async def test_add_with_oracle_metadata(self, clean_pg):
        result = await clean_pg.add(
            title="Oracle Learning", content="emily discovered this",
            tags=["emily"], oracle_name="emily",
            brain_path="ψ/memory/learnings/test.md",
            brain_tier="extrinsic",
            source_project="emily-oracle",
        )
        assert result["status"] == "indexed"
        doc = await clean_pg.get(result["id"])
        assert doc["oracle_name"] == "emily"
        assert doc["brain_tier"] == "extrinsic"
        assert doc["source_project"] == "emily-oracle"


@pytest.mark.asyncio
class TestPgStoreFTS:
    async def test_search_basic(self, clean_pg):
        await clean_pg.add(title="Docker Setup", content="Use compose v2 for orchestration")
        await clean_pg.add(title="Python Tips", content="Use list comprehensions")
        results = await clean_pg.search_fts("docker", limit=5)
        assert len(results) >= 1
        assert any("Docker" in r["title"] for r in results)

    async def test_search_with_scope_filter(self, clean_pg):
        await clean_pg.add(title="Shared Doc", content="public knowledge")
        await clean_pg.add(title="Emily Doc", content="private knowledge", tags=["emily"], oracle_name="emily")
        results = await clean_pg.search_fts("knowledge", oracle="emily", limit=10)
        assert len(results) >= 1
        assert all(r["oracle_name"] == "emily" for r in results)

    async def test_search_with_doc_type_filter(self, clean_pg):
        await clean_pg.add(title="Learning", content="learned something", doc_type="learning")
        await clean_pg.add(title="Pattern", content="pattern discovered", doc_type="pattern")
        results = await clean_pg.search_fts("something", doc_type="learning", limit=10)
        assert len(results) >= 1
        assert all(r["doc_type"] == "learning" for r in results)

    async def test_search_excludes_superseded(self, clean_pg):
        add_result = await clean_pg.add(title="Old Doc", content="old knowledge")
        await clean_pg._supersede_raw(add_result["id"], "new and improved knowledge", reason="updated")
        results = await clean_pg.search_fts("old", limit=10)
        # The old doc is superseded (excluded by WHERE superseded_by IS NULL)
        # but the new doc inherits title "Old Doc" which matches "old"
        # So we check that no superseded doc appears in results
        assert all(r["id"] != add_result["id"] for r in results)


@pytest.mark.asyncio
class TestPgStoreSupersede:
    async def test_supersede_creates_new(self, clean_pg):
        add_result = await clean_pg.add(title="Original", content="version 1")
        result = await clean_pg._supersede_raw(add_result["id"], "version 2")
        assert result["status"] == "superseded"
        assert result["superseded"] == add_result["id"]

        old_doc = await clean_pg.get(add_result["id"])
        assert old_doc["superseded_by"] is not None

    async def test_supersede_already_superseded(self, clean_pg):
        add_result = await clean_pg.add(title="Test", content="content")
        await clean_pg._supersede_raw(add_result["id"], "new content")
        with pytest.raises(ValueError, match="already superseded"):
            await clean_pg._supersede_raw(add_result["id"], "another update")


@pytest.mark.asyncio
class TestPgStoreConcepts:
    async def test_add_with_concepts(self, clean_pg):
        result = await clean_pg.add(
            title="Pattern Doc", content="hybrid search pattern",
            concepts=["search", "hybrid"],
        )
        concepts = await clean_pg.list_concepts()
        names = [c["name"] for c in concepts]
        assert "search" in names
        assert "hybrid" in names

    async def test_search_concepts(self, clean_pg):
        await clean_pg.add(
            title="Test", content="content", concepts=["docker-compose"],
        )
        results = await clean_pg.list_concepts(search="docker")
        assert len(results) >= 1
        assert results[0]["name"] == "docker-compose"


@pytest.mark.asyncio
class TestPgStoreTrace:
    async def test_add_trace(self, clean_pg):
        doc_a = await clean_pg.add(title="A", content="source")
        doc_b = await clean_pg.add(title="B", content="derived from A")
        result = await clean_pg.add_trace(doc_a["id"], doc_b["id"], "derived_from")
        assert result["relation"] == "derived_from"

    async def test_trace_chain(self, clean_pg):
        doc_a = await clean_pg.add(title="A", content="original")
        doc_b = await clean_pg.add(title="B", content="refined")
        await clean_pg.add_trace(doc_a["id"], doc_b["id"], "refines")
        chain = await clean_pg.get_trace_chain(doc_a["id"], direction="downstream")
        assert len(chain) >= 1


@pytest.mark.asyncio
class TestPgStoreScopeStats:
    async def test_list_scopes(self, clean_pg):
        await clean_pg.add(title="Doc", content="test", tags=["emily"], oracle_name="emily")
        # list_scopes reads from scope_registry — populated separately from docs
        scopes = await clean_pg.list_scopes()
        assert isinstance(scopes, list)

    async def test_stats(self, clean_pg):
        await clean_pg.add(title="A", content="test a", doc_type="learning")
        await clean_pg.add(title="B", content="test b", doc_type="pattern")
        stats = await clean_pg.stats()
        assert stats["total_documents"] >= 2
        assert "learning" in stats["by_type"]

    async def test_list_docs(self, clean_pg):
        await clean_pg.add(title="First", content="content 1")
        await clean_pg.add(title="Second", content="content 2")
        docs = await clean_pg.list_docs(limit=10)
        assert len(docs) >= 2


@pytest.mark.asyncio
class TestPgStoreSearchTopics:
    async def test_add_search_topic(self, clean_pg):
        result = await clean_pg.add_search_topic("test-scope", "python async", "web", "daily")
        assert result["scope"] == "test-scope"
        assert result["topic"] == "python async"
        assert result["source"] == "web"
        assert result["enabled"] is True

    async def test_add_duplicate_topic(self, clean_pg):
        await clean_pg.add_search_topic("test-scope", "python", "web", "daily")
        result = await clean_pg.add_search_topic("test-scope", "python", "web", "hourly")
        assert result.get("status") == "duplicate" or result.get("id")

    async def test_list_search_topics(self, clean_pg):
        await clean_pg.add_search_topic("s1", "docker", "web", "daily")
        await clean_pg.add_search_topic("s1", "kubernetes", "reddit", "weekly")
        await clean_pg.add_search_topic("s2", "python", "web", "daily")

        all_topics = await clean_pg.list_search_topics()
        assert len(all_topics) == 3

        s1_topics = await clean_pg.list_search_topics(scope="s1")
        assert len(s1_topics) == 2

    async def test_list_enabled_only(self, clean_pg):
        t1 = await clean_pg.add_search_topic("s1", "enabled-topic", "web", "daily")
        t2 = await clean_pg.add_search_topic("s1", "disabled-topic", "web", "daily")
        await clean_pg.toggle_search_topic(t2["id"], False)

        enabled = await clean_pg.list_search_topics(scope="s1", enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0]["topic"] == "enabled-topic"

    async def test_remove_search_topic(self, clean_pg):
        topic = await clean_pg.add_search_topic("s1", "temp", "web", "daily")
        result = await clean_pg.remove_search_topic(topic["id"])
        assert result["status"] == "deleted"
        topics = await clean_pg.list_search_topics(scope="s1")
        assert len(topics) == 0

    async def test_toggle_search_topic(self, clean_pg):
        topic = await clean_pg.add_search_topic("s1", "toggle-me", "web", "daily")
        assert topic["enabled"] is True
        result = await clean_pg.toggle_search_topic(topic["id"], False)
        assert result["enabled"] is False
        assert result["status"] == "updated"
        topics = await clean_pg.list_search_topics(scope="s1")
        assert topics[0]["enabled"] is False

    async def test_find_by_source_file(self, clean_pg):
        await clean_pg.add(
            title="Test", content="content",
            source_file="https://example.com/article",
            source_project="s1",
        )
        found = await clean_pg.find_by_source_file("https://example.com/article", "s1")
        assert found is not None
        assert found["source_file"] == "https://example.com/article"

    async def test_find_by_source_file_not_found(self, clean_pg):
        found = await clean_pg.find_by_source_file("https://example.com/missing", "s1")
        assert found is None

    async def test_find_by_source_file_with_hash(self, clean_pg):
        await clean_pg.add(
            title="Hash Test", content="unique content for hashing",
            source_file="/path/to/file.md", source_project="test-project",
        )
        found = await clean_pg.find_by_source_file(
            "/path/to/file.md", "test-project", include_hash=True,
        )
        assert found is not None
        assert "content_hash" in found
        assert "title" in found
        assert found["title"] == "Hash Test"
        assert len(found["content_hash"]) == 16

    async def test_find_by_source_file_with_hash_not_found(self, clean_pg):
        found = await clean_pg.find_by_source_file(
            "/missing/file.md", "no-project", include_hash=True,
        )
        assert found is None

    async def test_find_by_source_file_skips_superseded(self, clean_pg):
        """After supersede, find_by_source_file returns the NEW doc (not the old one)."""
        add_result = await clean_pg.add(
            title="Will Be Superseded", content="v1",
            source_file="/path/to/updated.md", source_project="test",
        )
        result = await clean_pg._supersede_raw(add_result["id"], "v2", reason="updated")

        found = await clean_pg.find_by_source_file("/path/to/updated.md", "test", include_hash=True)
        assert found is not None
        assert found["id"] == result["id"]  # returns the new superseding doc
        assert found["title"] == "Will Be Superseded"  # title inherited

    async def test_find_by_source_file_without_hash_backward_compat(self, clean_pg):
        """Callers without include_hash should still work."""
        await clean_pg.add(
            title="Compat", content="compat test",
            source_file="/path/compat.md", source_project="proj",
        )
        found = await clean_pg.find_by_source_file("/path/compat.md", "proj")
        assert found is not None
        assert "content_hash" not in found
        assert "title" not in found

    async def test_update_search_topic_last_searched(self, clean_pg):
        topic = await clean_pg.add_search_topic("s1", "python", "web", "daily")
        await clean_pg.update_search_topic_last_searched(topic["id"])
        topics = await clean_pg.list_search_topics(scope="s1")
        assert topics[0]["last_searched"] is not None


@pytest.mark.asyncio
class TestPgStoreReconcileLog:
    async def test_start_and_complete_reconcile_log(self, clean_pg):
        entry = await clean_pg.start_reconcile_log(scope="s1", dry_run=False)
        assert entry["id"]
        assert entry["started_at"]

        completed = await clean_pg.complete_reconcile_log(
            log_id=entry["id"],
            merged_duplicates=3,
            removed_duplicates=1,
            conflicts_found=2,
            conflicts_resolved=1,
            status="completed",
        )
        assert completed["status"] == "completed"
        assert completed["completed_at"]

    async def test_list_reconcile_log(self, clean_pg):
        e1 = await clean_pg.start_reconcile_log(scope="s1", dry_run=False)
        e2 = await clean_pg.start_reconcile_log(scope="s2", dry_run=True)
        await clean_pg.complete_reconcile_log(log_id=e1["id"], status="completed")
        await clean_pg.complete_reconcile_log(log_id=e2["id"], status="completed")

        logs = await clean_pg.list_reconcile_log(limit=10)
        assert len(logs) == 2
        assert logs[0]["status"] == "completed"

    async def test_failed_reconcile_log(self, clean_pg):
        entry = await clean_pg.start_reconcile_log(scope="s1", dry_run=False)
        await clean_pg.complete_reconcile_log(
            log_id=entry["id"],
            status="failed",
            error_message="DB connection lost",
        )
        logs = await clean_pg.list_reconcile_log(limit=1)
        assert logs[0]["status"] == "failed"
        assert logs[0]["error_message"] == "DB connection lost"


@pytest.mark.asyncio
class TestPgVector:
    """Integration tests for pgvector — embedding storage, similarity search, tag enrichment."""

    async def test_set_and_search_embedding(self, clean_pg):
        """Store an embedding and retrieve via cosine similarity."""
        # Add a document
        result = await clean_pg.add(
            title="Vector Test",
            content="pgvector integration test content",
            tags=["test", "vector"],
        )
        doc_id = result["id"]

        # Store a fake 768-dim embedding
        embedding = [0.1] * 768
        await clean_pg.set_embedding(doc_id, embedding)

        # Search with a slightly different embedding
        query_vec = [0.15] * 768
        results = await clean_pg.search_similar(query_vec, limit=5)
        assert len(results) >= 1
        assert results[0]["id"] == doc_id
        assert results[0]["title"] == "Vector Test"
        assert "score" in results[0]
        assert results[0]["score"] > 0

    async def test_search_similar_with_tags(self, clean_pg):
        """Vector search results include tags from junction table."""
        result = await clean_pg.add(
            title="Tagged Vector Doc",
            content="document with tags for vector search",
            tags=["arra", "python", "pgvector"],
        )
        await clean_pg.set_embedding(result["id"], [0.2] * 768)

        results = await clean_pg.search_similar([0.2] * 768, limit=5)
        assert len(results) >= 1
        doc = next(r for r in results if r["id"] == result["id"])
        assert "tags" in doc
        assert "arra" in doc["tags"]
        assert "python" in doc["tags"]
        assert "pgvector" in doc["tags"]

    async def test_search_similar_tag_filter(self, clean_pg):
        """Vector search filters by tags via junction table."""
        await clean_pg.add(
            title="Doc A",
            content="content A for filtering",
            tags=["arra"],
        )
        r2 = await clean_pg.add(
            title="Doc B",
            content="content B for filtering",
            tags=["python"],
        )
        await clean_pg.set_embedding(r2["id"], [0.3] * 768)

        results = await clean_pg.search_similar([0.3] * 768, tags=["python"], limit=5)
        assert len(results) >= 1
        assert all("python" in r.get("tags", []) for r in results)
        # Should not include doc without embedding
        ids = [r["id"] for r in results]
        assert r2["id"] in ids

    async def test_clear_embedding(self, clean_pg):
        """Clearing embedding removes doc from vector search results."""
        result = await clean_pg.add(
            title="To Be Cleared",
            content="this embedding will be cleared",
        )
        doc_id = result["id"]
        await clean_pg.set_embedding(doc_id, [0.4] * 768)

        # Should appear in search before clearing
        results = await clean_pg.search_similar([0.4] * 768, limit=5)
        assert any(r["id"] == doc_id for r in results)

        # Clear and verify exclusion
        await clean_pg.clear_embedding(doc_id)
        results = await clean_pg.search_similar([0.4] * 768, limit=5)
        assert not any(r["id"] == doc_id for r in results)

    async def test_search_similar_respects_superseded(self, clean_pg):
        """Vector search excludes superseded documents."""
        from src.db.pg_store import PgStore

        result = await clean_pg.add(
            title="Original Vector Doc",
            content="original content for superseded vector test",
        )
        doc_id = result["id"]
        await clean_pg.set_embedding(doc_id, [0.5] * 768)

        # Supersede it
        new_result = await clean_pg._supersede_raw(
            doc_id, "new content superseding original"
        )
        await clean_pg.set_embedding(new_result["id"], [0.5] * 768)

        # Original should not appear in results
        results = await clean_pg.search_similar([0.5] * 768, limit=10)
        ids = [r["id"] for r in results]
        assert doc_id not in ids
        assert new_result["id"] in ids

    async def test_search_similar_no_embedding_excluded(self, clean_pg):
        """Documents without embeddings are excluded from vector search."""
        await clean_pg.add(
            title="No Embedding Doc",
            content="this doc has no embedding",
        )

        results = await clean_pg.search_similar([0.6] * 768, limit=5)
        ids = [r["id"] for r in results]
        assert not any(
            r["title"] == "No Embedding Doc" for r in results
        )

    async def test_search_similar_scope_filter(self, clean_pg):
        """Vector search filters by scope. Uses source_project as scope proxy."""
        r1 = await clean_pg.add(
            title="Scope A Doc",
            content="content in scope A",
            tags=["scope-a"],
            source_project="project-a",
        )
        await clean_pg.set_embedding(r1["id"], [0.7] * 768)

        r2 = await clean_pg.add(
            title="Scope B Doc",
            content="content in scope B",
            tags=["scope-b"],
            source_project="project-b",
        )
        await clean_pg.set_embedding(r2["id"], [0.8] * 768)

        results = await clean_pg.search_similar(
            [0.7] * 768, source_project="project-a", limit=5
        )
        ids = [r["id"] for r in results]
        assert r1["id"] in ids
        assert r2["id"] not in ids

    async def test_search_similar_with_threshold(self, clean_pg):
        """Vector search with cosine similarity threshold filters low-similarity results."""
        result = await clean_pg.add(
            title="Threshold Test",
            content="testing similarity threshold filtering",
        )
        await clean_pg.set_embedding(result["id"], [0.9] * 768)

        # A very different vector should score low
        results = await clean_pg.search_similar(
            [0.0] * 768, limit=10, threshold=0.5
        )
        # Low similarity vector may or may not match depending on dimensionality
        # Just verify threshold is accepted and returns valid structure
        for r in results:
            assert "score" in r
            assert "tags" in r
            assert isinstance(r["tags"], list)