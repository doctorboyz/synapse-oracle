"""Tests for HTTP API routes — FastAPI TestClient tests."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.api.routes import init_routes


@pytest_asyncio.fixture
async def client(clean_pg):
    init_routes(clean_pg, embedder_client=None, settings=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestAPISearch:
    @pytest.mark.asyncio
    async def test_search_fts(self, client, clean_pg):
        await clean_pg.add(title="Docker Tips", content="Use compose v2")
        resp = await client.post("/api/search", json={"query": "docker", "mode": "fts"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_search_hybrid_fallback(self, client, clean_pg):
        await clean_pg.add(title="Python Patterns", content="list comprehensions")
        resp = await client.post("/api/search", json={"query": "python", "mode": "hybrid"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_search_with_scope(self, client, clean_pg):
        await clean_pg.add(title="Shared", content="public info")
        await clean_pg.add(title="Emily", content="private info", tags=["emily"], oracle_name="emily")
        resp = await client.post("/api/search", json={"query": "info", "oracle": "emily", "mode": "fts"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        assert all(r["oracle_name"] == "emily" for r in results)


class TestAPIPush:
    @pytest.mark.asyncio
    async def test_push_basic(self, client, clean_pg):
        resp = await client.post("/api/push", json={
            "title": "Test Doc", "content": "hello world", "scope": "shared",
        })
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "indexed"

    @pytest.mark.asyncio
    async def test_push_with_concepts(self, client, clean_pg):
        resp = await client.post("/api/push", json={
            "title": "Concepts Doc", "content": "search patterns",
            "scope": "shared", "concepts": ["search", "pattern"],
        })
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "indexed"


class TestAPIWebhook:
    @pytest.mark.asyncio
    async def test_webhook_sets_source_type(self, client, clean_pg):
        resp = await client.post("/api/webhook", json={
            "title": "From Hook", "content": "auto-ingested", "scope": "shared",
        })
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "indexed"
        doc = await clean_pg.get(result["id"])
        assert doc["source_type"] == "webhook"

    @pytest.mark.asyncio
    async def test_webhook_with_secret_valid(self, client, clean_pg):
        from src.config import Settings
        from src.api.routes import init_routes
        from src.api.webhook_verify import sign_payload

        secret = "my-test-secret"
        settings = Settings(webhook_secret=secret)
        init_routes(clean_pg, embedder_client=None, settings=settings)

        import json as _json
        payload = {"title": "Secured", "content": "verified content", "scope": "shared"}
        body = _json.dumps(payload).encode("utf-8")
        signature = sign_payload(secret, body)

        resp = await client.post(
            "/api/webhook",
            content=body,
            headers={"x-webhook-signature": signature, "content-type": "application/json"},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "indexed"

    @pytest.mark.asyncio
    async def test_webhook_with_secret_invalid(self, client, clean_pg):
        from src.config import Settings
        from src.api.routes import init_routes

        secret = "my-test-secret"
        settings = Settings(webhook_secret=secret)
        init_routes(clean_pg, embedder_client=None, settings=settings)

        import json as _json
        payload = {"title": "Bad", "content": "content", "scope": "shared"}
        body = _json.dumps(payload).encode("utf-8")

        resp = await client.post(
            "/api/webhook",
            content=body,
            headers={"x-webhook-signature": "sha256=bad0000000000000000000000000000000000000000000000000000000000000", "content-type": "application/json"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_webhook_with_secret_missing(self, client, clean_pg):
        from src.config import Settings
        from src.api.routes import init_routes

        settings = Settings(webhook_secret="my-test-secret")
        init_routes(clean_pg, embedder_client=None, settings=settings)

        import json as _json
        payload = {"title": "NoSig", "content": "content", "scope": "shared"}
        body = _json.dumps(payload).encode("utf-8")

        resp = await client.post(
            "/api/webhook",
            content=body,
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 401


class TestAPILineWebhook:
    @pytest.mark.asyncio
    async def test_line_webhook_no_secret_500(self, client, clean_pg):
        resp = await client.post(
            "/api/line-webhook",
            json={"events": []},
            headers={"x-line-signature": "test"},
        )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_line_webhook_valid(self, client, clean_pg):
        from src.config import Settings
        from src.api.routes import init_routes
        import base64, hashlib, hmac, json as _json

        secret = "line-test-secret"
        settings = Settings(line_channel_secret=secret)
        init_routes(clean_pg, embedder_client=None, settings=settings)

        payload = {
            "events": [
                {
                    "type": "message",
                    "source": {"type": "user", "userId": "U1234567890123456789012345678abcd"},
                    "message": {"type": "text", "text": "This is a longer test message that should bypass the guided question flow", "id": "12345"},
                    "replyToken": "rt-abc",
                    "timestamp": 1234567890000,
                }
            ]
        }
        body = _json.dumps(payload).encode("utf-8")
        signature = base64.b64encode(
            hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        ).decode("utf-8")

        resp = await client.post(
            "/api/line-webhook",
            content=body,
            headers={"x-line-signature": signature, "content-type": "application/json"},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["created"] == 1
        assert result["skipped"] == 0

    @pytest.mark.asyncio
    async def test_line_webhook_invalid_signature(self, client, clean_pg):
        from src.config import Settings
        from src.api.routes import init_routes

        settings = Settings(line_channel_secret="secret")
        init_routes(clean_pg, embedder_client=None, settings=settings)

        resp = await client.post(
            "/api/line-webhook",
            json={"events": []},
            headers={"x-line-signature": "bad-sig"},
        )
        assert resp.status_code == 401


class TestAPISupersede:
    @pytest.mark.asyncio
    async def test_supersede(self, client, clean_pg):
        add_result = await clean_pg.add(title="Original", content="v1")
        resp = await client.post("/api/supersede", json={
            "old_id": add_result["id"], "new_content": "v2", "reason": "updated",
        })
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "superseded"


class TestAPITrace:
    @pytest.mark.asyncio
    async def test_add_trace(self, client, clean_pg):
        doc_a = await clean_pg.add(title="A", content="source")
        doc_b = await clean_pg.add(title="B", content="derived")
        resp = await client.post("/api/trace", json={
            "source_id": doc_a["id"], "target_id": doc_b["id"],
            "relation": "derived_from", "confidence": 0.9,
        })
        assert resp.status_code == 200
        result = resp.json()
        assert result["relation"] == "derived_from"

    @pytest.mark.asyncio
    async def test_trace_chain(self, client, clean_pg):
        doc_a = await clean_pg.add(title="A", content="source")
        doc_b = await clean_pg.add(title="B", content="derived")
        await clean_pg.add_trace(doc_a["id"], doc_b["id"], "refines")
        resp = await client.get(f"/api/trace/{doc_a['id']}?direction=downstream")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1


class TestAPIConcepts:
    @pytest.mark.asyncio
    async def test_list_concepts(self, client, clean_pg):
        await clean_pg.add(title="Doc", content="content", concepts=["docker"])
        resp = await client.get("/api/concepts")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_search_concepts(self, client, clean_pg):
        await clean_pg.add(title="Doc", content="content", concepts=["docker-compose"])
        resp = await client.get("/api/concepts?search=docker")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1


class TestAPIGetDocument:
    @pytest.mark.asyncio
    async def test_get_document(self, client, clean_pg):
        add_result = await clean_pg.add(title="Fetch Me", content="some content")
        resp = await client.get(f"/api/documents/{add_result['id']}")
        assert resp.status_code == 200
        doc = resp.json()
        assert doc["title"] == "Fetch Me"

    @pytest.mark.asyncio
    async def test_get_document_not_found(self, client, clean_pg):
        resp = await client.get("/api/documents/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestAPIList:
    @pytest.mark.asyncio
    async def test_list_documents(self, client, clean_pg):
        await clean_pg.add(title="First", content="content 1")
        await clean_pg.add(title="Second", content="content 2")
        resp = await client.get("/api/documents")
        assert resp.status_code == 200
        docs = resp.json()
        assert len(docs) >= 2


class TestAPIScopes:
    @pytest.mark.asyncio
    async def test_list_scopes(self, client, clean_pg):
        # list_scopes reads from scope_registry — populated by register_project
        await clean_pg.add_search_topic("test-scope", "topic", "web", "daily")
        resp = await client.get("/api/scopes")
        assert resp.status_code == 200
        scopes = resp.json()
        assert isinstance(scopes, list)


class TestAPIStats:
    @pytest.mark.asyncio
    async def test_stats(self, client, clean_pg):
        await clean_pg.add(title="A", content="test a", doc_type="learning")
        resp = await client.get("/api/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total_documents"] >= 1


class TestAPISearchTopics:
    @pytest.mark.asyncio
    async def test_add_search_topic(self, client, clean_pg):
        resp = await client.post("/api/search-topics", json={
            "scope": "test-scope",
            "topic": "python async",
            "source": "web",
            "frequency": "daily",
        })
        assert resp.status_code == 200
        result = resp.json()
        assert result["scope"] == "test-scope"
        assert result["topic"] == "python async"
        assert result["source"] == "web"

    @pytest.mark.asyncio
    async def test_list_search_topics(self, client, clean_pg):
        await clean_pg.add_search_topic("test-scope", "docker", "web", "daily")
        await clean_pg.add_search_topic("test-scope", "kubernetes", "reddit", "weekly")
        resp = await client.get("/api/search-topics?scope=test-scope")
        assert resp.status_code == 200
        topics = resp.json()
        assert len(topics) == 2
        assert all(t["scope"] == "test-scope" for t in topics)

    @pytest.mark.asyncio
    async def test_remove_search_topic(self, client, clean_pg):
        topic = await clean_pg.add_search_topic("test-scope", "temp", "web", "daily")
        resp = await client.delete(f"/api/search-topics/{topic['id']}")
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_toggle_search_topic(self, client, clean_pg):
        topic = await clean_pg.add_search_topic("test-scope", "toggle-me", "web", "daily")
        assert topic["enabled"] is True
        resp = await client.post(f"/api/search-topics/{topic['id']}/toggle", json={"enabled": False})
        assert resp.status_code == 200
        result = resp.json()
        assert result["enabled"] is False


class TestAPIReconcileLog:
    @pytest.mark.asyncio
    async def test_list_reconcile_log(self, client, clean_pg):
        await clean_pg.start_reconcile_log(scope="s1", dry_run=False)
        await clean_pg.start_reconcile_log(scope="s2", dry_run=True)
        resp = await client.get("/api/reconcile-log?limit=10")
        assert resp.status_code == 200
        logs = resp.json()
        assert len(logs) == 2


class TestAPIHealth:
    @pytest.mark.asyncio
    async def test_health_ok(self, client, clean_pg):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        health = resp.json()
        assert health["status"] == "ok"
        assert health["pg"] is True