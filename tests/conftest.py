"""Test configuration — shared V2 fixtures for PostgreSQL-based tests."""

import os

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from src.config import Settings
from src.db.pg_store import PgStore
from src.embed.ollama import OllamaEmbedder
from src.ingest.push import Push
from src.retrieve.hybrid_search import HybridSearch

# Default to the dedicated throwaway test DB — NEVER the production vault.
# The clean_pg fixture wipes every table; pointing it at `synapse` would
# destroy the live vault (ISSUE-009 retro 2026-10-08).
TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://admin:88888888@localhost:5432/synapse_test",
)

# Hard isolation (ISSUE-010): force every Settings() constructed inside a
# test — including ones built internally by init_scan and friends — onto the
# throwaway DB. SYNAPSE_DB_URL outranks DATABASE_URL in config.py, so a
# developer shell exporting SYNAPSE_DB_URL=production would otherwise leak
# test writes into the live vault. Pin the dedicated var for this process.
os.environ["SYNAPSE_DB_URL"] = TEST_DB_URL

# Module-level store, created per-event-loop
_pg_store: PgStore | None = None
_schema_initialized = False


@pytest_asyncio.fixture
async def pg_store():
    global _pg_store, _schema_initialized
    settings = Settings()
    settings.database_url = TEST_DB_URL
    store = PgStore(settings)
    await store.connect()
    if not _schema_initialized:
        await store.init_schema()
        _schema_initialized = True
    yield store
    await store.close()


@pytest_asyncio.fixture
async def clean_pg(pg_store):
    async with pg_store.pool.acquire() as conn:
        # Clear self-referencing FK first to avoid FK violations
        await conn.execute("UPDATE knowledge_documents SET superseded_by = NULL")
        await conn.execute("DELETE FROM document_concepts")
        await conn.execute("DELETE FROM document_tags")
        await conn.execute("DELETE FROM trace")
        await conn.execute("DELETE FROM supersede_log")
        await conn.execute("DELETE FROM document_chunks")
        await conn.execute("DELETE FROM alert_log")
        await conn.execute("DELETE FROM scheduled_tasks")
        await conn.execute("DELETE FROM tag_rules")
        await conn.execute("DELETE FROM obsidian_sync_log")
        await conn.execute("DELETE FROM knowledge_documents")
        await conn.execute("DELETE FROM concepts")
        await conn.execute("DELETE FROM tags")
        await conn.execute("DELETE FROM scope_registry")
        await conn.execute("DELETE FROM search_topics")
        await conn.execute("DELETE FROM reconcile_log")
        await conn.execute("DELETE FROM pending_reviews")
    return pg_store


@pytest.fixture
def embedder():
    return None


@pytest_asyncio.fixture
def push(clean_pg, embedder):
    return Push(clean_pg, embedder)


@pytest_asyncio.fixture
def search(clean_pg, embedder):
    return HybridSearch(clean_pg, embedder)


@pytest_asyncio.fixture
def app_components(clean_pg, push, search):
    return clean_pg, push, search


@pytest_asyncio.fixture
async def api_client(clean_pg):
    from src.api.routes import init_routes
    from src.main import app

    init_routes(clean_pg, embedder_client=None, settings=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client