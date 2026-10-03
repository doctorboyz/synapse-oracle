# Synapse v4 — Architecture Analysis

## Overview

Synapse is an "agent-first knowledge service for the Oracle ecosystem" — a local-first, async Python application serving as a centralized knowledge vault backed by PostgreSQL with pgvector. Four entry points: FastAPI HTTP API, MCP stdio server, CLI (20+ subcommands), and LINE Bot webhook.

- **Version**: v4.0.0
- **Python**: >= 3.12
- **Total source**: ~21,000 lines across 40+ source files

## Directory Structure

```
src/
├── main.py                  # FastAPI app + CLI entry point (26 subcommands)
├── cli.py                   # Components container + async setup/teardown
├── config.py                # Settings dataclass (env vars + YAML)
├── cache.py                 # Thread-safe LRU + TTL search cache
├── registry.py              # Project registration (PostgreSQL-backed)
├── daemon.py                # PID file, signal handling
├── scheduler.py             # Background tasks: scan + reconcile + topic monitor
├── local_only.py            # Localhost URL enforcement
├── api/                     # HTTP API layer
│   ├── routes.py            # 30+ endpoints under /api/
│   ├── line_handler.py      # LINE webhook processor
│   └── webhook_verify.py    # HMAC-SHA256 verification
├── mcp/server.py            # 18 MCP tools via stdio
├── db/
│   ├── pg_store.py          # PostgreSQL CRUD, FTS, vector, chunks, concepts, trace
│   └── schema.sql           # Idempotent schema
├── embed/ollama.py          # Async Ollama embedder with retry + batching
├── llm/openrouter_client.py # OpenRouter API client with Ollama fallback
├── retrieve/hybrid_search.py # RRF fusion: dense (pgvector) + sparse (tsvector)
├── ingest/                  # Knowledge ingestion
│   ├── push.py              # Push pipeline: dedup, embed, chunk, trace
│   ├── init_scan.py         # Directory scanner
│   ├── concepts.py          # Concept extraction
│   ├── oracle_paths.py      # κ/ψ path mapping
│   ├── obsidian_links.py    # [[wikilink]] parser
│   └── obsidian_writer.py   # Obsidian vault writer
├── reconcile/               # Knowledge quality
│   ├── __init__.py           # Orchestrator: defrag + detox
│   ├── defrag.py            # Duplicate compaction
│   ├── detox.py             # LLM conflict detection
│   └── llm.py               # LLM analysis + summarization
├── connectors/              # External data sources
│   ├── topic_monitor.py     # Scheduled web/social monitoring
│   ├── web_search.py        # Serper, Tavily, DuckDuckGo
│   └── social_search.py     # X, Reddit, HN
├── migrate/                 # Data migration
│   ├── scope_to_tags.py     # scope → tags migration
│   └── vault_migrator.py    # Oracle vault import
└── hooks/                   # Claude Code integration
    ├── installer.py
    └── synapse-context-inject.sh
```

## Entry Points

### FastAPI App + CLI (`main.py`)
- FastAPI app at module level, startup: connect PG → init schema → restore registry → init Ollama → start scheduler
- CLI: 26 subcommands via `COMMAND_DISPATCH` dict
- `synapse serve` — uvicorn on SYNAPSE_HOST:SYNAPSE_PORT (default 0.0.0.0:8420)
- `synapse mcp` — MCP stdio server

### MCP Server (`mcp/server.py`)
- 18 MCP tools via stdio: synapse_search, synapse_push, synapse_supersede, synapse_trace, synapse_trace_chain, synapse_concepts, synapse_get, synapse_scope, synapse_tags, synapse_stats, synapse_list, synapse_register, synapse_unregister, synapse_projects, synapse_search_cross, synapse_reconcile_log, synapse_write_to_obsidian

### HTTP API (`api/routes.py`)
- 30+ endpoints under `/api/`: search, push, supersede, trace, concepts, documents, scopes, tags, stats, health, webhook, line-webhook, register, ingest (youtube/website/file), chat (streaming), write-to-obsidian, suggest-tags, search-topics, reconcile-log, models

## Core Abstractions

### PgStore (1006 lines)
Central data access object. All DB operations flow through this class.
- Connection: asyncpg.Pool (2-10 connections), pgvector codec
- CRUD: add(), get(), supersede(), list_docs()
- Search: search_fts() (tsvector + ILIKE RRF), search_similar() (pgvector cosine)
- Embedding: set_embedding(), clear_embedding(), search_chunks()
- Concepts/Tags: list_concepts(), list_tags()
- Trace: add_trace(), get_trace_chain() (BFS walk)
- Chunks (v4): add_chunk(), set_chunk_embedding(), search_chunks()

### OllamaEmbedder (64 lines)
Async embeddings with exponential backoff (2 retries), 4-concurrent batch semaphore, 4000-char truncation.

### HybridSearch (153 lines)
Three-mode search: dense (pgvector), fts (tsvector+ILIKE), hybrid (RRF 0.6/0.4, k=60). Graceful FTS fallback.

### Push (249 lines)
Ingestion pipeline: validate doc_type → extract concepts → semantic dedup (0.85 threshold) → store (content hash dedup) → trace links → embed → chunk (1500 chars, 200 overlap).

### Settings (145 lines)
30+ fields from env vars. YAML config support. Hot-reload via SIGHUP.

## Dependency Direction

```
api/ ← mcp/ ← cli.py
  ↓
ingest/ ← retrieve/ ← reconcile/ ← connectors/
  ↓
embed/ ← llm/ ← config.py
  ↓
db/pg_store.py → asyncpg → PostgreSQL+pgvector
```

Strictly downward. No circular dependencies.

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Language | Python >=3.12 |
| Database | PostgreSQL + pgvector (asyncpg) |
| API | FastAPI + Uvicorn |
| MCP | mcp SDK >=1.0.0 |
| Embeddings | Ollama (nomic-embed-text, 768-dim) |
| LLM | OpenRouter (primary) + Ollama (fallback) |
| FTS | PostgreSQL tsvector ('simple' config) |
| Vector | pgvector IVFFlat, cosine distance (<=>) |
| Search Fusion | RRF (k=60, weights 0.6/0.4) |
| LINE | Messaging API, HMAC-SHA256 |

## v4 Changes from v3

| Aspect | v3 | v4 |
|--------|----|----|
| Vector store | PostgreSQL + Qdrant | PostgreSQL pgvector only |
| Schema | Basic tables | + document_chunks, tag_rules, scheduled_tasks, alert_log, obsidian_sync_log |
| Chunking | None | 1500-char chunks with 200-char overlap |
| Tag classification | scope-based | tag-based (scope_to_tags migration) |

## Critical Issues

1. **HIGH**: SQL injection in `pg_store.py:504` — f-string interpolation for `relation` filter
2. **HIGH**: Hardcoded DB credentials in default DATABASE_URL (`config.py:18`)
3. **HIGH**: API listens on 0.0.0.0 with no authentication
4. **MEDIUM**: `get()` chain only follows 1 level of supersession
5. **MEDIUM**: `api_chat()` accesses `embedder.settings` without None check
6. **MEDIUM**: Stale version string `3.0.0` in `__init__.py`
7. **LOW**: `cli_command` decorator defined but never used
8. **LOW**: `summarize_with_llm()` defined but not called by init_scan
