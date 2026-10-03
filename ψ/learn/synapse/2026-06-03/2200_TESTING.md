# Synapse v4 — Testing Reference (2026-06-03)

## Test Infrastructure

- **Framework**: pytest + pytest-asyncio (asyncio_mode = "auto")
- **Database**: Real PostgreSQL (testcontainers or local) — no mocks for PgStore
- **Test count**: 567+ tests passing (as of May 28)
- **Config**: pyproject.toml → testpaths = ["tests"]

## Key Fixtures (conftest.py)

| Fixture | Purpose | Scope |
|---------|---------|-------|
| `pg_store` | Connected PgStore with schema | function |
| `clean_pg` | Empty DB (deletes all tables) | function |
| `push` | Push pipeline (no embedder) | function |
| `search` | HybridSearch (no embedder) | function |
| `app_components` | (clean_pg, push, search) tuple | function |
| `api_client` | httpx AsyncClient with ASGITransport | function |

## Test Categories

### Storage Tests (test_pg_store.py)
- CRUD: add, get, supersede, list_docs
- FTS: search_fts with Thai + English
- Vector: search_similar with pgvector
- Tags: CRUD, enrichment, junction table
- Concepts: CRUD, search
- Traces: add, get_chain, walk
- Scheduled tasks: create, get_due, resolve
- Tag rules: upsert, get, list
- Reconcile log: start, complete, list
- Pending reviews: create, confirm, cancel, expire

### Search Tests (test_hybrid_search.py)
- RRF fusion: dense + FTS merge
- Fallback: dense-only, FTS-only
- Cross-scope: multi-scope search
- Cache: hit/miss, TTL expiry

### API Tests (test_api_routes.py)
- All endpoints: search, push, supersede, trace, get, list, scopes, tags, concepts, stats, health, reconcile, register, unregister, projects, search-cross, chat, write-to-obsidian, models

### LINE Tests (test_line_handler.py, test_line_handler_v2.py)
- Message classification: text, image, video, audio, file
- Question detection: Thai + English patterns
- Task detection: date extraction, priority
- Auto-ingest: push pipeline integration
- Slash commands: /search, /recent, /stats, /help

### Integration Tests (test_lifecycle.py)
- Startup → connect → init schema → register project → push → search → cleanup
- Registry backup/restore

### Reconcile Tests
- Defrag: exact + semantic dedup
- Detox: conflict detection + merge
- LLM: conflict analysis prompt

## Testing Patterns

### Mock Strategy
- Ollama: always None in default fixtures (graceful degradation)
- External APIs (LINE, OpenRouter, Serper): mocked via httpx
- PgStore: real database, never mocked

### Common Test Pattern
```python
@pytest_asyncio.fixture
async def clean_pg(pg_store):
    async with pg_store.pool.acquire() as conn:
        await conn.execute("DELETE FROM document_tags")
        await conn.execute("DELETE FROM knowledge_documents")
        # ... truncate all tables
    return pg_store

async def test_search_returns_results(clean_pg):
    pg = clean_pg
    await pg.add(title="Test", content="hello world", tags=["test"])
    results = await pg.search_fts("hello")
    assert len(results) > 0
```

### Important: Patch the Source Module
From learnings: When `startup()` does `from src.registry import restore_registry_backup`, patch `src.registry.restore_registry_backup`, not `src.main.restore_registry_backup`.
