"""ISSUE-009 causal tests — unqualified created_at breaks tags-filtered queries.

Root cause hypothesis: search_fts() and list_docs() join document_tags + tags
when a tags filter is present. The tags table has its own created_at column,
so every unqualified `created_at` in the SELECT list / ORDER BY becomes
ambiguous to Postgres and the query fails.

These tests exercise that exact mechanism: with a tags filter over a real
Postgres schema, both methods must return rows instead of raising
'column reference "created_at" is ambiguous'.

Isolation: runs on a throwaway database (synapse_cpt_issue009) created and
dropped per session. Never touches the vault database.
"""

import os

import asyncpg
import pytest
import pytest_asyncio

from src.config import Settings
from src.db.pg_store import PgStore

ADMIN_URL = os.getenv(
    "TEST_ADMIN_DB_URL",
    "postgresql://admin:88888888@localhost:5432/postgres",
)
TEST_DB_NAME = "synapse_cpt_issue009"
TEST_DB_URL = f"postgresql://admin:88888888@localhost:5432/{TEST_DB_NAME}"


@pytest_asyncio.fixture
async def issue009_store():
    """Create a throwaway DB with the real schema; drop it afterwards."""
    admin = await asyncpg.connect(ADMIN_URL)
    await admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"')
    await admin.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    await admin.close()

    # pgvector must exist before PgStore.connect() — pool connections register
    # the vector codec at creation, before init_schema() would install it.
    fresh = await asyncpg.connect(TEST_DB_URL)
    await fresh.execute("CREATE EXTENSION IF NOT EXISTS vector")
    await fresh.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    await fresh.close()

    settings = Settings()
    settings.database_url = TEST_DB_URL
    store = PgStore(settings)
    await store.connect()
    await store.init_schema()

    await store.add(
        title="Retro alpha",
        content="deploy went fine but monitoring gaps need follow up",
        doc_type="retro",
        tags=["issue009", "deploy"],
        scope="issue009-test",
    )
    await store.add(
        title="Retro beta",
        content="on-call rotation improved after the runbook change",
        doc_type="retro",
        tags=["issue009"],
        scope="issue009-test",
    )

    yield store

    await store.close()
    admin = await asyncpg.connect(ADMIN_URL)
    await admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"')
    await admin.close()


@pytest.mark.asyncio
class TestTagsFilteredQueries:
    async def test_list_docs_with_tags_filter(self, issue009_store):
        """list_docs must resolve created_at against knowledge_documents only."""
        rows = await issue009_store.list_docs(tags=["issue009"])
        assert len(rows) == 2
        assert all(r["created_at"] for r in rows)

    async def test_search_fts_with_tags_filter(self, issue009_store):
        """search_fts (FTS + ILIKE paths) must survive the tags join."""
        rows = await issue009_store.search_fts("deploy", tags=["issue009"])
        assert len(rows) == 1
        assert rows[0]["title"] == "Retro alpha"

    async def test_search_fts_ilike_path_with_tags(self, issue009_store):
        """The ILIKE phase has its own ORDER BY created_at — cover it too."""
        rows = await issue009_store.search_fts("runbook", tags=["issue009"])
        assert len(rows) == 1
        assert rows[0]["title"] == "Retro beta"