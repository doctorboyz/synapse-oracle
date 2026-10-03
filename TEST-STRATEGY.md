# Synapse v4 — Test Strategy

> pytest + asyncpg + real pgvector for integration

## Test Structure

```
tests/
├── conftest.py                  # Shared fixtures (PG pool, settings mock)
├── test_pg_store.py             # PostgreSQL CRUD, FTS, vector, tags
├── test_push.py                 # Push pipeline (dedup, embed, supersede)
├── test_hybrid_search.py        # Hybrid search RRF fusion
├── test_line_handler.py         # LINE event processing + commands
├── test_line_handler_v2.py      # LINE additional scenarios
├── test_api_routes.py           # HTTP API endpoints
├── test_lifecycle.py            # Full lifecycle: push → search → supersede
├── test_mcp_server.py           # MCP stdio server
├── test_cache.py                # LRU + TTL search cache
├── test_concepts.py             # Concept extraction + linking
├── test_config.py               # Settings + YAML config
├── test_daemon.py               # PID file, signals, lifecycle
├── test_init_scan.py            # File scanning + summarization
├── test_local_only.py           # URL validation
├── test_reconcile_defrag.py     # Duplicate compaction
├── test_reconcile_detox.py      # LLM conflict detection
├── test_reconcile_llm.py        # Reconcile LLM integration
├── test_registry.py             # Project registry
├── test_scheduler.py            # Background scanning
├── test_vault_migrator.py       # Vault migration
└── test_hooks_installer.py      # Hook installer
```

## Test Types

### Unit Tests
- Pure logic: formatting helpers, task detection, URL validation, config parsing
- Mock external dependencies (LINE API, OpenRouter, Ollama)

### Integration Tests
- **Real PostgreSQL required** for: pg_store, push, hybrid_search, lifecycle
- Tests marked with `@pytest.mark.integration` or use `pg` fixture
- CI needs pgvector container (pgvector/pgvector:pg17)

### E2E Tests
- LINE bot: webhook → process → reply (mock LINE API responses)
- API: full push → search → supersede cycle

## Coverage Target

80%+ line coverage on src/

Current: ~96.9% test pass rate (550/567), 17 failures are PG integration tests needing connection fix

## Running Tests

```bash
# All tests
pytest tests/ -v

# Unit tests only (no PG needed)
pytest tests/ -v -k "not pg_store and not push and not lifecycle"

# Integration tests (needs PG)
pytest tests/ -v -m integration

# With coverage
pytest tests/ --cov=src --cov-report=term-missing
```

## Known Gaps

1. **No CI pipeline** — Tests run manually on Mac mini
2. **PG integration tests fail** when database isn't running — need test DB setup script
3. **No E2E tests** for LINE webhook (mock-based only)
4. **No performance/load tests**
5. **asyncpg vector codec** — Mock-based tests don't catch type serialization bugs
6. **OpenRouter/LLM responses** — Mocked, real API behavior may differ
