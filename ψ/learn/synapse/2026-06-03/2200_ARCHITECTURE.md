# Synapse v4 Architecture — Deep Learn (2026-06-03)

> Full codebase analysis from source. 16,677 lines of Python across 44 source modules + 7,523 lines of tests.

## Version

**v4.0.0** — PostgreSQL + pgvector single-source-of-truth (Qdrant removed in v4 migration, May 27)

## Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Database | PostgreSQL + pgvector | Canonical store, FTS (tsvector), vector similarity |
| Embeddings | Ollama (nomic-embed-text, 768-dim) | Dense vector generation |
| LLM | OpenRouter (fallback: Ollama qwen2.5:7b) | Summarization, conflict analysis, OCR |
| Web | FastAPI + Uvicorn | HTTP API (port 8420) |
| CLI | argparse (20+ subcommands) | Terminal interface |
| MCP | mcp SDK (stdio) | Agent-first tool access |
| Messaging | LINE Messaging API | Chat-based knowledge ingestion |
| Search | Custom hybrid (RRF 60/40) | Dense + FTS fusion |

## Entry Points (4)

1. **CLI** (`src/main.py:cli_main` → `COMMAND_DISPATCH`) — 25+ subcommands
2. **HTTP API** (`src/api/routes.py` → 25+ endpoints under `/api/*`)
3. **MCP Server** (`src/mcp/server.py` → 15 tools via stdio)
4. **Hook Handler** (`src/ingest/claude_hook.py` → PostToolUse auto-ingest)

## Core Data Flow

```
Input → Push Pipeline → PostgreSQL (canonical) + pgvector (embeddings)
                                    ↓
                            Hybrid Search (RRF fusion)
                                    ↓
                    CLI / API / MCP / LINE / Obsidian
```

### Push Pipeline
1. Validate doc_type (CONTENT_TYPES ∪ EVENT_TYPES)
2. Extract concepts (hashtags + CamelCase) if not provided
3. Semantic dedup check (pgvector similarity ≥ 0.85)
4. Insert into `knowledge_documents` (title, content, hash, metadata, tags via junction table)
5. Create traces from `[[Obsidian links]]`
6. Embed content (Ollama, max 4000 chars) → set pgvector embedding
7. Chunk long content (>1500 chars) → embed each chunk separately
8. Apply tag rules (auto-classify task/reminder/event → scheduled_tasks)

### Search Pipeline
1. Receive query → embed (Ollama)
2. Run dense search (pgvector cosine similarity) and FTS (PostgreSQL tsvector 'simple')
3. Merge via Reciprocal Rank Fusion (k=60, weights 0.6/0.4)
4. Tags merged via set union across both result lists
5. Cache result (LRU + TTL)
6. Return ranked results

## Schema (PostgreSQL)

### Main Tables
- `knowledge_documents` — UUID PK, title, content, content_hash, doc_type, scope (deprecated→tags), source_file, source_type, source_project, oracle_name, brain_path, brain_tier, concepts (JSONB), metadata (JSONB), superseded_by (FK self-ref), tsvector, embedding (vector(768)), summary, created_at, updated_at, archived_at
- `tags` — name (UNIQUE)
- `document_tags` — doc_id FK + tag_id FK (junction table)
- `concepts` — name (UNIQUE)
- `document_concepts` — doc_id FK + concept_id FK
- `trace` — source_id FK + target_id FK + relation + confidence
- `supersede_log` — old_id + new_id + reason + timestamp
- `registered_projects` — scope + project_path + registered_at
- `search_topics` — scope + topic + source + frequency + enabled
- `tag_rules` — tag_name + handler + config + auto_classify + alert_on_due
- `scheduled_tasks` — doc_id FK + tag_name + task_type + due_date + recurrence + status
- `alert_log` — task_id + doc_id + channel + message + status
- `obsidian_sync_log` — doc_id + vault_path + file_path + action + file_hash
- `reconcile_log` — scope + status + timestamps + stats
- `pending_reviews` — review data (LINE confirmation flow, mostly deprecated)
- `document_chunks` — chunk storage for long docs (chunk_index, content, embedding)

### Key Indexes
- GIN on `search_vector` (tsvector)
- Partial indexes on `scope`, `doc_type`, `oracle_name`, `brain_tier`, `source_project` (WHERE superseded_by IS NULL)
- IVFFlat on `embedding` (WHERE embedding IS NOT NULL)
- GIN on `metadata`

### SQL Functions
- `hybrid_search(query_text, query_embedding, scope_filter, doc_type_filter, tag_filter, result_limit)` — native SQL hybrid search with tag filtering via EXISTS subquery
- `update_search_vector()` trigger — auto-populate tsvector from title+content+concepts

## Module Map (by domain)

### Storage (`src/db/`)
- `pg_store.py` (1342 lines) — All PostgreSQL CRUD: add, get, supersede, search_fts, search_similar, search_chunks, set_embedding, clear_embedding, list_docs, list_scopes, stats, add_trace, get_trace_chain, tags, concepts, find_by_source_file, reconcile_log, pending_reviews, scheduled_tasks, alert_log, tag_rules, obsidian_sync_log, chunks, upsert_tag_rule, start/complete_reconcile_log
- `schema.sql` (366 lines) — Idempotent DDL with migrations inline

### Ingest (`src/ingest/`)
- `push.py` (267 lines) — Push pipeline: validate, dedup, insert, embed, chunk, trace
- `init_scan.py` (200 lines) — Directory scanner: walk files, extract metadata, push to vault
- `claude_hook.py` (100 lines) — PostToolUse auto-ingest for κ/ψ files
- `concepts.py` (25 lines) — Hashtag + CamelCase concept extraction
- `oracle_paths.py` (100 lines) — κ/ψ path → doc_type, oracle_name, brain_tier mapping
- `obsidian_links.py` (120 lines) — `[[Link]]` parser → trace creation
- `obsidian_writer.py` (140 lines) — Write docs to Obsidian vault as .md with frontmatter

### Retrieve (`src/retrieve/`)
- `hybrid_search.py` (158 lines) — RRF fusion (60/40), cross-scope search, cache integration

### Reconcile (`src/reconcile/`)
- `defrag.py` (205 lines) — Exact + semantic dedup via pgvector ANN
- `detox.py` (240 lines) — LLM conflict detection + merge + supersede
- `llm.py` (90 lines) — Ollama-based conflict analysis prompt

### Connectors (`src/connectors/`)
- `web_search.py` (150 lines) — Serper/Tavily/DuckDuckGo web search
- `social_search.py` (150 lines) — Twitter/Reddit/HN social search
- `topic_monitor.py` (90 lines) — Periodic topic monitoring scheduler

### Assistant (`src/assistant/`)
- `tag_rules.py` (140 lines) — Tag-based rule engine (task/reminder/event auto-classification)
- `scheduler.py` (90 lines) — Scheduled task alert via LINE push

### API (`src/api/`)
- `routes.py` (792 lines) — 25+ HTTP endpoints
- `line_handler.py` (1170 lines) — LINE webhook: message processing, OCR, Q&A, commands, auto-ingest
- `webhook_verify.py` (50 lines) — HMAC-SHA256 webhook signature verification

### MCP (`src/mcp/`)
- `server.py` (484 lines) — 15 MCP tools (synapse_search, push, supersede, trace, trace_chain, concepts, get, scope, stats, list, register, unregister, projects, search_cross, write_to_obsidian, ingest_session, reconcile_log)

### Infrastructure (`src/`)
- `main.py` (743 lines) — FastAPI app + CLI dispatcher + startup/shutdown
- `cli.py` (88 lines) — Components helper + JSON output
- `config.py` (145 lines) — Settings dataclass (env vars + YAML hot-reload)
- `cache.py` (75 lines) — LRU + TTL search cache
- `daemon.py` (199 lines) — PID file, signal handling, Docker detection
- `scheduler.py` (313 lines) — Background: scan, reconcile, topic monitor, alert loops
- `registry.py` (161 lines) — Project registration + backup/restore
- `local_only.py` (60 lines) — URL validation (localhost-only enforcement)
- `embed/ollama.py` (80 lines) — Async embedding with retry + batching

### Migration (`src/migrate/`)
- `vault_migrator.py` (138 lines) — v3 → v4 data migration
- `scope_to_tags.py` (124 lines) — Migrate scope-based to tag-based classification

## Document Types

### Content Types (no lifecycle)
knowledge, note, idea, insight, moment, good-to-know, reference, retro, pattern, protocol, instinct, wisdom, handoff, log

### Event Types (have status/due dates)
todo, not-to-do, reminder, event, payment, deadline

### Oracle Path Rules
κ/intrinsic/* → instinct (intrinsic)
κ/extrinsic/* → knowledge, reference, log (extrinsic)
ψ/memory/* → knowledge, retro (extrinsic)
ψ/outbox/* → handoff (extrinsic)

## Tag Rules Engine
- Default rules: `task` → create scheduled_task, `reminder` → alert on due, `event` → calendar awareness
- `auto_classify` → create scheduled_task on push
- `alert_on_due` → trigger LINE notification
- Date extraction from Thai + English content (relative days, Thai months, weekdays)

## LINE Integration
- Full text → auto-ingest pipeline
- Image/video → OCR via OpenRouter vision → auto-ingest
- Question detection (Thai + English) → synapse_search → formatted answer
- `/slash` commands: search, recent, stats, scopes, tags, help, ask
- Semantic dedup (DM) vs exact dedup (group)
- Task supersede on title match
- Tag rules auto-applied after push

## Frontend
- React + TypeScript + Vite (in `frontend/`)
- Standalone SPA, connects to HTTP API
