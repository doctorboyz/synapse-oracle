# Synapse v4 Quick Reference

> "The junction where knowledge connects." -- ความทรงจำของกองทัพ Oracle
> Version: 4.0.0 | Framework: Python 3.12+ | Database: PostgreSQL + pgvector

---

## 1. What Synapse v4 Does

Synapse is a **local-first hybrid knowledge framework** that acts as the shared memory/brain for the Oracle ecosystem. Think of it as a search engine for everything you and your agents have ever learned, written, or discussed.

### Core Capabilities (in plain language)

| Capability | What it means |
|---|---|
| **Ingest knowledge** | Push text, files, websites, YouTube transcripts, LINE messages, or any markdown into the vault. Everything gets embedded with AI vectors for semantic search. |
| **Hybrid search** | Search with both meaning (vector similarity) and keywords (full-text search), merged with Reciprocal Rank Fusion. You get the best of both worlds. |
| **LINE Bot** | A full LINE Messaging API bot that auto-ingests messages, answers questions via `/ask`, searches via `/search`, and understands images with OCR. |
| **Never delete** | Documents are superseded (replaced by newer versions), never deleted. Full audit trail via `supersede_log`. |
| **Knowledge graph** | Trace relationships between documents: `derived_from`, `refines`, `contradicts`, `extends`. Follow chains of knowledge evolution. |
| **Reconcile** | Deduplicate near-identical documents and detect conflicting information using LLM comparison. |
| **Obsidian integration** | Write knowledge to Obsidian vaults as `.md` files with YAML frontmatter and `[[wikilinks]]`. Bidirectional: Synapse writes to Obsidian, Obsidian edits feed back. |
| **3-way access** | CLI (terminal), MCP (Claude Code / agent tools), HTTP API (curl, Docker, webhooks). Same data, three interfaces. |
| **Project registry** | Register projects for cross-project search. Search across all your project knowledge at once. |
| **Search topics** | Monitor topics across web and social media (Serper, Tavily, Reddit, Hacker News, Twitter). Daily/hourly scheduled ingestion. |
| **Document chunks** | Long documents are automatically chunked (1500 chars, 200 overlap) for granular retrieval. |

### What Synapse is NOT

- NOT a file manager (Obsidian handles that)
- NOT a note editor (you use Obsidian, VS Code, or LINE)
- NOT a general-purpose database (PostgreSQL handles the persistence)
- NOT a replacement for CLAUDE.md or project docs (it supplements them)

---

## 2. Architecture Overview (v4: PostgreSQL-only)

### Version Evolution

| Version | Database | Vector Store | Status |
|---|---|---|---|
| v1 | SQLite | LanceDB (local files) | Legacy |
| v2 | SQLite + shared vault | LanceDB (shared) | Legacy |
| v3 | PostgreSQL + Qdrant | Qdrant (external vector DB) | Legacy |
| **v4** | **PostgreSQL only** | **pgvector extension** | **Current** |

In v4, Qdrant has been **fully removed**. All vector operations use PostgreSQL's `pgvector` extension. This simplifies the stack to a single database.

### System Architecture

```
                        ┌─────────────────────────────┐
                        │     3-Way Access Layer       │
                        │  CLI  │  MCP  │  HTTP API    │
                        └─────────────┬───────────────┘
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        │                      Synapse Core                          │
        │                                                             │
        │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐ │
        │  │  Ingest   │  │ Retrieve │  │ Reconcile│  │ Scheduler │ │
        │  │  (push)   │  │ (search) │  │(defrag+  │  │ (scan,    │ │
        │  │           │  │          │  │  detox)  │  │  topics)  │ │
        │  └─────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬─────┘ │
        │        │             │             │              │        │
        │        └─────────────┼─────────────┼──────────────┘        │
        │                      │             │                        │
        │              ┌───────┴───────┐     │                        │
        │              │  PostgreSQL   │     │                        │
        │              │  + pgvector   │◄────┘                        │
        │              │  + tsvector   │                               │
        │              └───────────────┘                               │
        └──────────────────────┬──────────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────────────────────┐
        │               External Services (localhost)                  │
        │  ┌──────────┐  ┌──────────┐  ┌───────────────────────────┐ │
        │  │  Ollama  │  │ OpenRouter│  │  LINE Messaging API      │ │
        │  │ (embed,  │  │ (LLM API) │  │  (bot webhooks)          │ │
        │  │  LLM)    │  │           │  │                           │ │
        │  └──────────┘  └──────────┘  └───────────────────────────┘ │
        └─────────────────────────────────────────────────────────────┘
```

### Key Schema Tables

| Table | Purpose |
|---|---|
| `knowledge_documents` | Main document store with `embedding vector(768)`, `search_vector tsvector`, `superseded_by` |
| `document_chunks` | Chunked long documents with per-chunk embeddings |
| `supersede_log` | Audit trail of all document replacements |
| `trace` | Knowledge graph edges (source -> target with relation type) |
| `concepts` + `document_concepts` | Many-to-many concept tagging |
| `tags` + `document_tags` | Many-to-many tag classification |
| `scope_registry` | Legacy scope tracking |
| `registered_projects` | Project registry for cross-project search |
| `search_topics` | Web/social monitoring topic configuration |
| `reconcile_log` | Audit trail of defrag/detox runs |
| `pending_reviews` | LINE confirmation flow (legacy, unused in current flow) |
| `tag_rules` + `scheduled_tasks` + `alert_log` | Tag-based assistant infrastructure |
| `obsidian_sync_log` | Obsidian sync tracking |

### Hybrid Search (RRF Fusion)

```
Query "docker compose patterns"
    │
    ├─► pgvector cosine similarity (60% weight) ─► dense_results
    │
    └─► tsvector FTS + ILIKE (40% weight) ─► fts_results
            │                                  │
            └────────── RRF k=60 ──────────────┘
                          │
                    merged & ranked
                          │
                   search cache (LRU + TTL)
```

The FTS path uses both `tsvector` (for English/token-based search) and `ILIKE` (for Thai/mixed-language and substring matches), merged with internal RRF. This dual-pass approach ensures Thai content is findable even when tsvector tokenization is imperfect.

---

## 3. Installation

### Option A: pip install (development mode)

```bash
cd /path/to/synapse
pip install -e .

# With dev dependencies (for testing)
pip install -e ".[dev]"
```

### Option B: Docker Compose

```bash
cd docker/
# Copy and edit .env with your secrets
cp .env.example .env
# Start (requires infra-oracle network with PostgreSQL already running)
docker-compose up -d
```

### Prerequisites

| Requirement | Purpose |
|---|---|
| **Python 3.12+** | Runtime |
| **PostgreSQL 14+** with `pgvector` and `pgcrypto` extensions | Data store + vector search |
| **Ollama** (optional but recommended) | Local embeddings + LLM fallback |
| **OpenRouter API key** (optional) | Cheap cloud LLM for summarization, Q&A, OCR |

### PostgreSQL Setup

```sql
CREATE DATABASE synapse;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

Schema is auto-created on first run (`synapse serve` calls `init_schema()` which is idempotent).

---

## 4. Environment Variables (.env)

### Required

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql://admin:88888888@localhost:5432/synapse` | PostgreSQL connection string (also accepts `SYNAPSE_DB_URL`) |

### Ollama (Embeddings + LLM)

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model name |
| `EMBEDDING_DIM` | `768` | Vector dimension (must match model) |
| `EMBEDDING_TIMEOUT` | `30` | Seconds per embedding call |

### API Server

| Variable | Default | Purpose |
|---|---|---|
| `SYNAPSE_HOST` | `0.0.0.0` | HTTP API bind address |
| `SYNAPSE_PORT` | `8420` | HTTP API port |

### Daemon

| Variable | Default | Purpose |
|---|---|---|
| `SYNAPSE_PID_FILE` | `~/.synapse/synapse.pid` | PID file path |
| `SYNAPSE_SCAN_INTERVAL` | `0` (disabled) | Seconds between auto-scans (e.g., `600` = 10 min) |
| `SYNAPSE_RECONCILE_HOUR` | `2` | Hour of day (0-23) for auto-reconcile; `-1` to disable |

### Search

| Variable | Default | Purpose |
|---|---|---|
| `SEARCH_WEIGHTS` | `0.6,0.4` | Dense/FTS RRF weights |
| `CACHE_TTL` | `300` | Search cache TTL in seconds |
| `CACHE_MAX_SIZE` | `1000` | Max cached queries |

### OpenRouter (Cloud LLM)

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | (empty) | API key for OpenRouter |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | API endpoint |
| `OPENROUTER_MODEL` | `google/gemini-2.0-flash-001` | Default chat/synthesis model |
| `OPENROUTER_VISION_MODEL` | `google/gemini-2.0-flash-001` | OCR/vision model |
| `OPENROUTER_SUMMARY_MODEL` | `deepseek/deepseek-chat-v3-0324` | Summarization model |
| `OPENROUTER_TIMEOUT` | `60` | Seconds before timeout |

### LINE Messaging API (Bot)

| Variable | Default | Purpose |
|---|---|---|
| `LINE_CHANNEL_SECRET` | (empty) | HMAC signature verification |
| `LINE_CHANNEL_ACCESS_TOKEN` | (empty) | Bot reply token |

### Web Search

| Variable | Default | Purpose |
|---|---|---|
| `SERPER_API_KEY` | (empty) | Serper.dev API key for web search |
| `TAVILY_API_KEY` | (empty) | Tavily API key (alternative) |
| `WEB_SEARCH_PROVIDER` | `serper` | Which provider to use (`serper` or `tavily`) |

### Obsidian

| Variable | Default | Purpose |
|---|---|---|
| `OBSIDIAN_VAULT_PATH` | (empty) | Path to Obsidian vault root |

### Webhook Security

| Variable | Default | Purpose |
|---|---|---|
| `SYNAPSE_WEBHOOK_SECRET` | (empty) | HMAC secret for webhook verification |

### Topic Monitor

| Variable | Default | Purpose |
|---|---|---|
| `SYNAPSE_TOPIC_INTERVAL` | `3600` | Seconds between topic monitor runs; `0` to disable |

### Logging

| Variable | Default | Purpose |
|---|---|---|
| `SYNAPSE_LOG_LEVEL` | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## 5. How to Run

### Start the API Server (primary mode)

```bash
# Directly
synapse serve

# With all env vars set
DATABASE_URL=postgresql://admin:88888888@localhost:5432/synapse \
OLLAMA_URL=http://localhost:11434 \
synapse serve
```

This starts FastAPI on port 8420, connects to PostgreSQL, initializes schema, and optionally starts the scheduler (if `SYNAPSE_SCAN_INTERVAL > 0` or `SYNAPSE_RECONCILE_HOUR >= 0`).

### Start MCP Server (for Claude Code)

```bash
synapse mcp
```

This runs an MCP stdio server with 17 tools available to Claude Code.

### Docker

```bash
cd docker/
docker-compose up -d
```

### Check Status

```bash
synapse status              # Daemon status + database stats
synapse stats               # Vault statistics only
```

### Stop the Daemon

```bash
synapse stop
```

---

## 6. Key Features with Examples

### 6.1 Push Knowledge

**Push text:**
```bash
synapse push --title "Docker Compose Patterns" \
  --content "# Docker patterns\n\nAlways use version '3.9'..." \
  --tags "docker,infrastructure" \
  --doc-type pattern
```

**Push a file:**
```bash
synapse push --file /path/to/document.md --tags "my-project,python"
```

**Response:**
```json
{
  "id": "a1b2c3d4-...",
  "status": "indexed",
  "tags": ["my-project", "python"]
}
```

**Status values:**
- `indexed` — New document added + embedded
- `duplicate` — Exact content hash match (skipped)
- `semantic_duplicate` — Near-duplicate detected via pgvector similarity (>85%)

### 6.2 Search (Hybrid)

```bash
# Default hybrid search (pgvector + tsvector → RRF)
synapse search "docker compose patterns"

# Dense-only (vector similarity)
synapse search "infrastructure patterns" --mode dense

# FTS-only (keyword)
synapse search "redis" --mode fts

# With filters
synapse search "async" --tags "python,backend" --doc-type pattern --limit 5
```

**Result fields:** `id`, `title`, `scope`, `doc_type`, `oracle_name`, `source_project`, `score`, `content` (first 500 chars), `tags`, `created_at`

### 6.3 LINE Bot

Synapse includes a full LINE Messaging API bot via `POST /api/line-webhook`.

**How it works:**
1. Any LINE text message >= 10 chars → auto-ingested as `doc_type=note`
2. Image messages → OCR via OpenRouter vision model → ingested
3. Task detection: messages with dates, `@ mentions`, status keywords → `doc_type=task`
4. Task updates auto-supersede existing tasks (same title + tag)
5. Group/room messages also ingested (no confirmation DM in groups)
6. Stickers and short texts (< 10 chars) are skipped

**LINE Commands:**

| Command | Action |
|---|---|
| `/search <query>` | Full-text search across all scopes |
| `/ask <question>` | LLM-powered Q&A with context from the vault |
| `/recent [scope]` | Last 5 documents |
| `/stats` | Total documents + scopes |
| `/tags` | List all tags with doc counts |
| `/help` | Show help message |

**LINE LLM via OpenRouter:**
- `/ask` does cross-scope search (10 results), builds context, sends to OpenRouter with a Thai-first system prompt
- Answer includes sources with doc titles, types, and tags
- Falls back to search results if OpenRouter is unavailable

### 6.4 Reconcile (Defrag + Detox)

```bash
# Full reconcile (dedup + conflict detection)
synapse reconcile

# Dry run (show what would change without changing)
synapse reconcile --dry-run

# Cross-scope (compare across all tags using pgvector ANN)
synapse reconcile --cross-scope

# Limit to specific scope
synapse reconcile --scope my-project

# View reconcile history
synapse reconcile --history --limit 10
```

**What reconcile does:**
- **Defrag**: Finds near-duplicate documents (similarity >= 95%) and merges them
- **Detox**: Finds potentially conflicting documents (similarity >= 70%) and uses LLM to detect actual contradictions, then resolves them

### 6.5 MCP Tools (17 total)

Available in Claude Code when the MCP server is configured:

| Tool | Purpose |
|---|---|
| `synapse_search` | Hybrid search with filters (tags, doc_type, oracle, concepts, mode) |
| `synapse_push` | Add knowledge with auto-detected oracle metadata |
| `synapse_supersede` | Replace a document (old doc never deleted) |
| `synapse_trace` | Create relationship between two documents |
| `synapse_trace_chain` | Follow the chain of related documents |
| `synapse_concepts` | List/search concepts across the vault |
| `synapse_get` | Get full document by ID with supersession chain |
| `synapse_scope` | List scopes (deprecated, use tags) |
| `synapse_tags` | List/search tags with document counts |
| `synapse_stats` | Vault stats: total, by type, by scope, by oracle |
| `synapse_list` | List documents with filters (scope, tags, doc_type, oracle) |
| `synapse_register` | Register a project for cross-project search |
| `synapse_unregister` | Remove a project registration |
| `synapse_projects` | List all registered projects |
| `synapse_search_cross` | Search across multiple scopes |
| `synapse_reconcile_log` | View reconcile audit history |
| `synapse_write_to_obsidian` | Write documents to Obsidian vault as .md with [[wikilinks]] |

### 6.6 Cross-Project Search

```bash
# Register projects first
synapse register --path /path/to/project-a --scope proj-a
synapse register --path /path/to/project-b --scope proj-b

# Search across them
synapse search-cross "docker patterns" --scopes proj-a,proj-b
```

### 6.7 Knowledge Graph (Trace)

```bash
# Link two documents
synapse trace --source <uuid-a> --target <uuid-b> --relation derived_from

# Available relations: derived_from, refines, contradicts, extends

# Follow the chain
synapse trace-chain <uuid-a> --direction both --max-depth 5
```

Obsidian-style `[[wikilinks]]` in document content are automatically resolved and created as trace links on push.

### 6.8 Obsidian Integration

**Write to Obsidian vault:**
```bash
# Via API
curl -X POST localhost:8420/api/write-to-obsidian \
  -H "Content-Type: application/json" \
  -d '{"doc_id": "uuid-here"}'

# Via MCP tool
# synapse_write_to_obsidian with doc_id or query
```

**Auto-write on scan:**
When the scheduler scans an Obsidian vault and detects changed files, it auto-writes updated versions back to the vault.

---

## 7. Common Commands (Complete Reference)

### Server & Daemon

```bash
synapse serve                      # Start HTTP API (port 8420)
synapse mcp                        # Start MCP stdio server (17 tools)
synapse stop                       # Stop running daemon
synapse status                     # Daemon status + DB stats + local-only violations
synapse install-hooks              # Register hooks in ~/.claude/settings.json
```

### Knowledge Operations

```bash
synapse push --title "T" --content "C" --tags "tag1,tag2" --doc-type pattern
synapse push --file path/to/doc.md --tags "my-project" --concepts "async,python"
synapse search "query" --tags "tag1" --mode hybrid --limit 10
synapse search-cross "query" --scopes proj-a,proj-b --limit 10
synapse get <uuid>
synapse list --tags "my-project" --limit 20 --offset 0 --order newest
```

### Tags & Concepts

```bash
synapse tags --search "python" --limit 50
synapse concepts --search "async" --limit 50
synapse scope                      # List scopes only (deprecated)
```

### Document Evolution

```bash
synapse supersede <old-uuid> --new-content "Updated content" --reason "correction"
synapse trace --source <uuid-a> --target <uuid-b> --relation derived_from --confidence 0.9
synapse trace-chain <uuid> --direction both --max-depth 5
```

### Init & Maintenance

```bash
synapse init --path /my/project --tags "my-project" --dry-run
synapse scan                       # Scan all registered projects for new/changed files
synapse reconcile --scope my-project --cross-scope --dry-run
synapse reconcile --history        # View reconcile audit log
```

### Project Management

```bash
synapse register --path /my/project --scope my-project
synapse unregister my-project
synapse projects                   # List all registered projects
```

### Search Topics (Web/Social Monitoring)

```bash
synapse topic-add --scope my-project --topic "kubernetes patterns" --source web --frequency daily
synapse topic-list --scope my-project --enabled-only
synapse topic-run                  # Manually trigger topic monitor
synapse topic-remove <topic-uuid>
```

### Statistics

```bash
synapse stats                      # JSON: total_docs, by_type, by_scope, by_oracle
```

---

## 8. LINE Bot Usage

Configure your LINE bot webhook to point to `POST /api/line-webhook`.

### Commands (type in LINE chat)

| Command | Example | What it does |
|---|---|---|
| `/ask <question>` | `/ask วิธี deploy Docker บน server` | LLM answers using knowledge base context (10 results from cross-scope search) |
| `/search <query>` | `/search postgres pgvector` | Full-text search across all scopes |
| `/tags` | `/tags` | List all tags with document counts |
| `/recent [scope]` | `/recent my-project` | Last 5 documents |
| `/stats` | `/stats` | Total documents and tags count |
| `/help` | `/help` | Show all available commands |

### Auto-Ingest Behavior

- **Text messages** >= 10 chars → auto-ingested as `note`
- **Images** → OCR via OpenRouter vision (Gemini Flash) → ingested as `note`
- **Videos/Audio** → stored with `needs_transcription` metadata flag
- **Locations** → stored with lat/lng coordinates
- **Tasks** (detected via date patterns, `@mentions`, status keywords) → auto-ingested as `task`; updates auto-supersede existing tasks
- **Stickers** → skipped
- **Short texts** (< 10 chars) → skipped
- **Group chats** → ingested silently (no confirmation replies)

---

## 9. HTTP API Endpoints (18 endpoints on port 8420)

### Core Operations

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/search` | Hybrid search |
| `POST` | `/api/push` | Add knowledge |
| `POST` | `/api/supersede` | Replace document |
| `POST` | `/api/trace` | Create trace link |
| `GET` | `/api/trace/{doc_id}` | Follow trace chain |
| `GET` | `/api/concepts` | List/search concepts |
| `GET` | `/api/documents/{doc_id}` | Get full document |
| `GET` | `/api/documents` | List documents with filters |
| `GET` | `/api/scopes` | List scopes |
| `GET` | `/api/tags` | List tags |
| `GET` | `/api/stats` | Vault statistics |

### Health

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Full health (pg + embedding status) |
| `GET` | `/api/health/live` | Liveness probe |
| `GET` | `/api/health/ready` | Readiness probe |

### Project Management

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/register` | Register project |
| `POST` | `/api/unregister` | Remove registration |
| `GET` | `/api/projects` | List registered projects |
| `POST` | `/api/search-cross` | Cross-project search |

### Ingestion

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/ingest/youtube` | Extract transcript from YouTube URL |
| `POST` | `/api/ingest/website` | Scrape and ingest website content |
| `POST` | `/api/ingest/file` | Upload file (PDF, DOCX, TXT, MD) |
| `POST` | `/api/line-webhook` | LINE Messaging API webhook |

### LLM & Intelligence

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/chat` | Streaming chat with search context + LLM |
| `POST` | `/api/suggest-tags` | LLM-suggested tags for content |
| `GET` | `/api/models` | List available Ollama models |

### Obsidian

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/write-to-obsidian` | Write docs to Obsidian vault |
| `POST` | `/api/resolve-links` | Resolve `[[wikilinks]]` to document IDs |

### Webhooks & Topics

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/webhook` | Generic webhook (HMAC-secured) |
| `GET` | `/api/reconcile-log` | Reconcile audit history |
| `GET/POST/DELETE` | `/api/search-topics` | CRUD search topics |

---

## 10. Testing

```bash
# Run all tests
pytest tests/ -v

# Specific test file
pytest tests/test_pg_store.py -v

# With coverage
pytest tests/ --cov=src --cov-report=term-missing
```

### Test Files (30 test files)

| Test File | What it Covers |
|---|---|
| `test_pg_store.py` | PostgreSQL CRUD, FTS, vector search, supersede, concepts, trace, chunks |
| `test_line_handler.py`, `test_line_handler_v2.py` | LINE webhook, commands, OCR, auto-ingest, task detection |
| `test_api_routes.py` | All 18 HTTP endpoints |
| `test_mcp_server.py` | All 17 MCP tools |
| `test_hybrid_search.py` | RRF fusion, search modes, cross-scope search |
| `test_push.py` | Push pipeline, dedup, chunking, embedding |
| `test_reconcile_defrag.py` | Duplicate detection and merging |
| `test_reconcile_detox.py` | LLM conflict detection |
| `test_reconcile_llm.py` | LLM integration for reconcile |
| `test_config.py` | Settings, YAML loading, env vars |
| `test_cache.py` | LRU + TTL search cache |
| `test_daemon.py` | PID file, signal handling, start/stop/status |
| `test_scheduler.py` | Scheduled scanning, reconcile scheduling |
| `test_registry.py` | Project register/unregister/list |
| `test_embed.py` | Ollama embedding, retry, batching |
| `test_openrouter_client.py` | OpenRouter chat, summarize, OCR |
| `test_obsidian_writer.py` | Obsidian .md writing with YAML and wikilinks |
| `test_obsidian_links.py` | Wikilink resolution and trace creation |
| `test_init_scan.py` | Directory scanning + LLM summarization |
| `test_vault_migrator.py` | Vault migration |
| `test_oracle_paths.py` | Path → oracle metadata extraction |
| `test_concepts.py` | Concept extraction |
| `test_connectors.py` | Web/social search connectors |
| `test_hooks_installer.py` | Claude Code hooks installation |
| `test_webhook_verify.py` | HMAC signature verification |
| `test_local_only.py` | Local-only URL validation |
| `test_lifecycle.py` | Full server lifecycle (startup/shutdown) |
| `test_cli.py` | CLI argument parsing and command dispatch |

---

## 11. Code Quality Analysis

### 11.1 Dead Code Detection

#### Unused Imports

The `__init__.py` files across `src/api/`, `src/db/`, `src/embed/`, `src/ingest/`, `src/llm/`, `src/mcp/`, `src/reconcile/`, `src/retrieve/`, `src/connectors/`, `src/hooks/`, `src/migrate/` are all **empty** (`__init__.py` with no content). These exist only for package namespace and are not dead code.

#### Unused Functions / Classes

No unused functions or classes detected. All exported functions in major modules are wired through CLI dispatch (`COMMAND_DISPATCH` in main.py) or the API router.

#### Commented-Out Code Blocks

No commented-out code blocks found in the source. The codebase is clean.

#### Legacy v3 Patterns Surviving v4 Migration

- **`scope` column in `knowledge_documents`**: The SQL schema still has a `scope TEXT` column. The codebase has migrated to a `tags` junction table (`tags` + `document_tags`), but scope is still used internally in many queries. The CLI flags `--scope` are marked deprecated in help text but still functional. **This is intentional backward compatibility** -- the scope column persists for now.
- **`tags JSONB` column**: Deprecated per the schema comment (`-- tags JSONB deprecated in favour of tags + document_tags junction tables`), but still present in the table and populated. `list_docs()` still reads from the JSONB column.
- **`scope_registry` table**: Still referenced in `list_scopes()` but essentially superseded by the `tags` junction table.
- **`/api/suggest-scope` endpoint**: Marked deprecated, forwards to `/api/suggest-tags`.
- **`Pending reviews` table + methods**: Full CRUD methods exist in `PgStore` (`create_pending_review`, `get_pending_review_for_user`, etc.) and the schema has `pending_reviews` table, but the current LINE handler no longer uses confirmation flow -- it auto-ingests directly. The pending review infrastructure is **dead code** for the current flow, kept for potential future use.
- **`CONFIRM_YES`, `CONFIRM_NO`, `CONFIRM_EDIT` keyword sets** in `line_handler.py` (lines 19-21): Imported but never referenced since the confirmation flow was removed. **Dead constants.**

### 11.2 Correctness Issues

#### Potential Bugs

| Location | Issue | Severity |
|---|---|---|
| `pg_store.py:66-73` | Content-hash dedup uses a **16-char hex truncated hash** (`hashlib.sha256(content.encode()).hexdigest()[:16]`). This is only 64 bits of hash space. For a knowledge vault with thousands of documents, collision probability is non-trivial (birthday paradox: ~2^32 inserts before 50% collision chance). | Low |
| `pg_store.py:67-69` | Hash dedup query runs `SELECT id FROM knowledge_documents WHERE content_hash = $1` **without filtering out superseded documents**. A superseded document with the same hash as new content will incorrectly trigger a "duplicate" status. | Medium |
| `line_handler.py:742-750` | `pusher` (Push instance) is instantiated lazily inside the event loop with a fresh `OllamaEmbedder` per batch. If settings change during processing, the old embedder is used. | Low |
| `api/routes.py:19-23` | Module-level globals (`pg`, `embedder`, `push`, `search`, `_settings`) are set by `init_routes()`. If called multiple times (e.g., config reload), stale references persist on the module globals. The new values replace them but any async tasks holding old references will use the old objects. | Low |
| `config.py:17-18` | `DATABASE_URL` fallback checks `SYNAPSE_DB_URL` env var which is not documented. If both are unset, defaults to `postgresql://admin:88888888@localhost:5432/synapse` -- hardcoded credentials in source. | Low |

#### Error Handling Gaps

| Location | Issue |
|---|---|
| `main.py:66-69` | `OllamaEmbedder(settings)` instantiation wrapped in bare `except Exception`. If Ollama is unavailable, embedder is set to `None` and the server runs without embeddings. However, the `log.warning` uses `format` string syntax that might fail if `e` has no string representation. |
| `main.py:427-428` | `get_components()` in `cmd_status` is wrapped in try/except, but if the database is down, the error message is just `{"error": str(e)}` embedded in the status JSON -- no distinction between "DB down" vs "table missing" vs "permission denied". |
| `mcp/server.py:243-245` | Same bare `except Exception` for OllamaEmbedder in MCP server -- identical issue. |
| `api/routes.py:234-248` | Health endpoint catches `Exception` from pg but returns `"degraded"` -- the actual error is swallowed, making debugging hard. |
| `line_handler.py:753-762` | `pusher.push_text()` inside `try/except` wraps all errors as `"Auto-push failed"`. If a schema mismatch causes all pushes to fail, every message silently produces an error reply with no differentiation. |
| `push.py:156-163` | Chunk embedding failures log a warning but continue -- partial chunks mean incomplete retrieval for that document without any indication to the caller. |

#### Edge Cases Not Handled

| Scenario | Location | Risk |
|---|---|---|
| Empty document content | `pg_store.py:61` | `hashlib.sha256("".encode())` produces a valid hash. Pushing empty content creates a document with no meaningful content but a valid embedding (all zeros or random). |
| Supersede of already-superseded doc | `pg_store.py:150` | Query filters `superseded_by IS NULL`. If two concurrent requests supersede the same doc, second wins silently. No optimistic locking. |
| Concurrent reconcile | `pg_store.py:719-754` | `start_reconcile_log` and `complete_reconcile_log` are separate calls. If reconcile crashes between them, a "running" log entry persists forever with no cleanup. |
| Ollama returns wrong dimension vector | `pg_store.py:320-327` | `set_embedding()` passes the raw vector from Ollama directly to PostgreSQL. If the model changes dimensions, this fails at the database level with a cryptic error. |
| LINE reply token expiry | `line_handler.py:804-822` | LINE reply tokens expire after a few minutes. Long-running OCR or LLM calls may produce a reply after the token expires. The error is caught but logged only as debug. |

### 11.3 Best Practice Violations

#### Anti-Patterns

| Pattern | Location(s) | Why it's problematic |
|---|---|---|
| **Module-level mutable globals** | `api/routes.py:19-23` (`pg`, `embedder`, `push`, `search`, `_settings = None`) | These globals are set during startup and read by every request handler. There is no lock, no thread safety. FastAPI runs async but with multiple workers, these would be per-process. Fine for single-worker, but a code smell. |
| **Bare except clauses** | `main.py:67-69`, `mcp/server.py:243-245`, `push.py:159-160`, `line_handler.py:552-553` | Catching bare `Exception` hides unexpected errors (MemoryError, KeyboardInterrupt, etc.). Should catch specific exceptions. |
| **Dynamic import inside async handler** | `line_handler.py:743` (`from src.ingest.push import Push` inside `process_line_events`) | Importing inside an async function body is a side effect. It works but means every LINE event batch triggers import resolution. |
| **`__import__` for fallback access** | `push.py:29`, `api/routes.py:716,545` | Using `__import__("src.config").Settings()` as a fallback when `embedder.settings` is unavailable. This is a code smell -- Settings should be injected via dependency injection. |
| **String-replace for schema path** | `pg_store.py:32` (`__file__.replace("pg_store.py", "schema.sql")`) | Fragile -- breaks if the file is renamed or moved. Should use `os.path.join(os.path.dirname(__file__), "schema.sql")` or `importlib.resources`. |

#### Naming Inconsistencies

| Issue | Location(s) |
|---|---|
| **Mixed Thai/English in logs** | Throughout the codebase. `log.info("Chunked doc %s into %d chunks ...")` in push.py vs Thai messages in line_handler.py. This is intentional (hybrid language) but inconsistent. |
| **`scope` vs `tags` parameter names** | CLI uses `--scope` (deprecated) and `--tags`. MCP tools accept both `scope` and `tags`. Internal functions use `scope` parameter name. The mixing of old/new terminology creates confusion. |
| **`source_project` vs `scope` semantics** | `source_project` tracks "which project sent this", while `scope`/`tags` classify content. In `push.py:119`, `source_project=source_project or scope` -- fallback logic conflates the two concepts. |
| **`brain_tier` values** | Docstring says "intrinsic/extrinsic" but no validation exists. |
| **`oracle_name` in `list_docs`** | Parameter is `oracle` but internal column is `oracle_name`. CLI uses `--oracle`, MCP uses `oracle`. |

#### Missing Validation/Security Checks

| Issue | Location | Risk |
|---|---|---|
| **No content length limit** | `pg_store.py:46-60` | No max length check on `content`. A very large string (e.g., 10MB) could be inserted, creating a huge tsvector and embedding. |
| **No title length limit** | Schema: `TEXT NOT NULL` | No constraint. Titles could be megabytes. |
| **No rate limiting on API** | `api/routes.py` | No per-IP or per-token rate limiting. The push/search endpoints are unauthenticated and unbounded. |
| **No input sanitization on title/tags** | `pg_store.py:46-60` | User-supplied strings like `title` and `tags` are directly interpolated into SQL (via `$N` placeholders -- safe from injection) but not sanitized for length or content. |
| **HMAC verification off by default** | `api/routes.py:99-112` | Webhook signature verification depends on `SYNAPSE_WEBHOOK_SECRET` being set. If empty, verification is skipped. This is documented behavior but easy to miss in production. |
| **LINE signature verification failure returns 401** | `api/routes.py:128-129` | Correct, but the error message `"Invalid LINE signature"` leaks that signature verification is configured, which could help an attacker confirm the endpoint is live. |

### 11.4 Testing Gaps

#### Coverage Summary

The test suite has **30 test files** covering most modules. However:

| What IS tested | What IS NOT tested |
|---|---|
| PgStore CRUD, FTS, vector search | Concurrent access patterns (multiple simultaneous pushes, race on hash dedup) |
| LINE commands (/search, /ask, /help, /recent, /stats, /tags) | LINE webhook under high message volume (100+ events per batch) |
| Hybrid search RRF fusion | Search behavior with 100K+ documents (scale testing) |
| Reconcile defrag and detox | Reconcile with cross-scope + 1000 near-duplicates |
| Push pipeline (dedup, chunking, embedding) | Push with Ollama down (graceful degradation) |
| MCP server tools (all 17) | MCP server under concurrent tool calls |
| Config YAML loading and SIGHUP reload | Config hot-reload while search is in progress |
| Cache LRU eviction and TTL expiry | Cache under rapid repeated identical queries |
| Obsidian writer (single doc + search results) | Obsidian writer when vault is on a network mount (latency) |
| OpenRouter client (chat, summarize, OCR) | OpenRouter with API key rotation or rate limit handling |

#### Critical Paths Without Adequate Coverage

| Path | Risk |
|---|---|
| **Scheduled scan with file changes** | `scheduler.py` triggers `scan_once()` → `supersede_and_reindex()` in `push.py`. This path involves: file hash check → supersede → clear_embedding → re-embed → chunk_and_embed. Tests exist for push, but the full end-to-end path (scan → detect change → supersede → re-embed) is not explicitly tested. |
| **LINE auto-ingest with task supersede** | The `_find_existing_task()` → `pg.supersede()` path inside `process_line_events()` is complex. Tests cover individual pieces but not: LINE text → task detection → find existing → supersede → reply. |
| **Concurrent reconcile** | Reconcile has `start_reconcile_log` / `complete_reconcile_log` pairs. If two reconciles run simultaneously (e.g., scheduled + manual), there is no lock to prevent overlapping runs. |
| **Full daemon lifecycle** | `test_lifecycle.py` exists but the README mentions "daemon start/stop/status" -- need to verify signal handling (SIGTERM graceful shutdown, SIGHUP config reload) is tested under load. |

#### Test Quality Observations

| Observation | Impact |
|---|---|
| **Most tests mock Ollama at the HTTP level** (via `httpx` mocking). This means embedding failures are well-tested but actual vector quality is never assessed. | Medium -- embedding quality depends on model, not code. |
| **PgStore tests likely use a real PostgreSQL** (via `testcontainers[postgres]` in dev deps). This is good -- integration tests with real DB. | Positive |
| **No performance/benchmark tests** in the test suite. The README mentions v1 benchmarks but there are no automated latency or recall tests for v4. | Medium |
| **No fuzz testing** for API endpoints -- large payloads, malformed JSON, edge-case Unicode (emoji, RTL text). | Low |
| **LINE tests cover text, image, video, audio, location, sticker, file types** -- good coverage of message types. | Positive |

### 11.5 File Organization Recommendations

#### Files That Are Too Large (>800 lines)

| File | Lines | Recommendation |
|---|---|---|
| **`src/db/pg_store.py`** (1005 lines) | **CRITICAL** — largest file in the project | **Split into**: `pg_store.py` (core CRUD + schema, ~300 lines) + `pg_search.py` (FTS, vector, hybrid SQL function, ~300 lines) + `pg_reviews.py` (pending reviews CRUD, ~150 lines) + `pg_chunks.py` (document chunks, ~100 lines) + `pg_topics.py` (search topics, ~100 lines) |
| **`src/api/line_handler.py`** (822 lines) | **LARGE** — 2nd largest | **Split into**: `line_handler.py` (main event processor, ~300 lines) + `line_commands.py` (command handlers: search, ask, recent, stats, help, ~200 lines) + `line_media.py` (media download + OCR, ~150 lines) + `line_tasks.py` (task detection + parsing, ~170 lines) |
| **`src/api/routes.py`** (792 lines) | **LARGE** — 3rd largest | **Split into**: `routes.py` (core: search, push, supersede, trace, get, list, stats, ~250 lines) + `routes_ingest.py` (youtube, website, file upload, ~150 lines) + `routes_obsidian.py` (write-to-obsidian, resolve-links, ~100 lines) + `routes_topics.py` (search topics CRUD, ~100 lines) + `routes_health.py` (health + models, ~50 lines) + `routes_chat.py` (chat + suggest-tags, ~140 lines) |
| **`src/main.py`** (734 lines) | **LARGE** — CLI entry point | **Split into**: `main.py` (FastAPI app + lifecycle, ~100 lines) + `cli_commands.py` (all `_cmd_*` implementations, ~450 lines) + `cli_parser.py` (argument parser `build_parser()`, ~180 lines). The parser itself is 137 lines of `add_parser`/`add_argument` calls. |

#### Code in Wrong Place

| Current Location | Issue | Suggested Location |
|---|---|---|
| `src/api/routes.py` contains `_extract_youtube_id()` (private function at module level, line 362-373) | URL parsing utility mixed into API routes | `src/ingest/url_utils.py` or inline in the youtube ingest handler |
| `src/api/routes.py` contains `_parse_file_content()` (private function, line 481-510) | File parsing utility (PDF, DOCX, TXT) mixed into API routes | `src/ingest/file_parser.py` |
| `src/ingest/push.py` contains `chunk_text()` (static method, line 74-86) | Text chunking logic belongs in its own module | `src/ingest/chunker.py` (shared by push and init_scan) |
| `src/llm/openrouter_client.py` contains `_ollama_summarize()` and `_ollama_ocr()` (module-level private functions) | Ollama fallback logic mixed into OpenRouter client | `src/llm/ollama_fallback.py` or inline in a base LLM client class |
| `src/config.py` contains `DEFAULT_CONFIG_PATH` at module level (line 11) | Hardcoded path | Should be configurable via env var `SYNAPSE_CONFIG` (already supported in `Settings.config_path`) |

#### Duplicate Logic Across Files

| Logic | Found In | Recommendation |
|---|---|---|
| **Ollama embedder instantiation with try/except** | `main.py:66-69`, `mcp/server.py:242-245`, `line_handler.py:743-750` | **Consolidate** into `src/embed/ollama.py` as a factory function: `create_embedder(settings) -> OllamaEmbedder | None` |
| **Search → build context → LLM call pattern** | `api/routes.py:572-655` (chat endpoint), `line_handler.py:271-317` (`_answer_question`), `line_handler.py:386-426` (`/ask` command) | **Consolidate** into `src/retrieve/rag.py` — a reusable RAG (Retrieval-Augmented Generation) helper: `async def rag_query(query, pg, search, llm_client) -> dict` |
| **Scope/tag list rendering** | `line_handler.py:42-65` (`_format_source_line`) and `line_handler.py:68-84` (`_format_source_context`) | These format functions are LINE-specific but the formatting logic (title + type + oracle + source + tags) is generic. **Extract** to `src/format/doc_render.py` |
| **Database URL fallback chain** | `config.py:17-18` only | The default credentials `admin:88888888` appear in both `config.py` default and `docker/.env`. **Centralize** defaults in one place (config.py) and have docker/.env override explicitly. |
| **`_ensure_list()` function** | `pg_store.py:984-996` | This utility is imported nowhere else. If other modules need it, move to `src/utils.py`. Currently only used inside PgStore methods. |

### 11.6 Security Scan (Quick)

#### Hardcoded Secrets

| Location | Secret | Risk |
|---|---|---|
| **`src/config.py:19`** | `postgresql://admin:88888888@localhost:5432/synapse` — hardcoded DB credentials as default | **HIGH** — visible in source. Mitigated: overridable via env var, but the default is a real-looking password. |
| **`tests/conftest.py:17-18`** | Same pattern likely in test DB URL default | **MEDIUM** — test config only, but if tests connect to a real DB with this default, accidental data exposure. |
| **`docker/.env`** | Real `OPENROUTER_API_KEY`, `LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN` | **CRITICAL** — this file is gitignored per `.env` comment but the file exists on disk with real secrets. Verify `.gitignore` includes `docker/.env`. |

#### Unsafe Input Handling

| Endpoint | Issue |
|---|---|
| `POST /api/ingest/youtube` | Accepts arbitrary URL → passed to `YouTubeTranscriptApi.get_transcript()`. No URL validation (could point to internal services). |
| `POST /api/ingest/website` | Accepts arbitrary URL → `httpx.get(url, follow_redirects=True)`. SSRF risk: attacker could probe internal network. Also no timeout validation (hardcoded 30s). |
| `POST /api/ingest/file` | Manual multipart boundary parsing with `body.split(f"--{boundary}".encode())`. If boundary contains regex special chars, parsing may fail or produce unexpected splits. |
| `POST /api/search` | No limit enforcement server-side beyond the request parameter. A client requesting `limit=1000000` would fetch and return enormous result sets. |
| `POST /api/push` | No content size limit. A multi-GB push would attempt to hash, store, and embed enormous content -- exhausting memory and DB storage. |

#### Missing Auth Checks

| Area | Issue | Risk |
|---|---|---|
| **All `/api/*` endpoints** | **No authentication whatsoever**. Anyone who can reach port 8420 can read/write/delete all knowledge. | **HIGH** for network-exposed deployments. Mitigated: `SYNAPSE_HOST=127.0.0.1` (localhost only) is recommended. Docker uses `0.0.0.0` with `extra_hosts` for host.docker.internal -- only accessible within Docker network. |
| **LINE webhook** | HMAC signature verification via `LINE_CHANNEL_SECRET` -- **good** if configured, skipped if empty. | **MEDIUM** — depends on operator setting the env var. |
| **Generic webhook** | HMAC via `SYNAPSE_WEBHOOK_SECRET` -- skipped if empty. | **MEDIUM** |
| **MCP server** | No authentication at the MCP protocol level -- relies on stdio transport (only accessible by local processes) | **LOW** -- stdio is inherently local-only. |

---

## 12. Summary: v4 Health Assessment

### Strengths

- **Clean v4 migration**: Qdrant fully removed, pgvector is the sole vector store, stack simplified.
- **Comprehensive test suite**: 30 test files covering nearly every module.
- **Good LINE integration**: Robust message type handling (text, image OCR, video/sticker/location), task supersede, group chat support.
- **Well-structured MCP tools**: 17 tools with clear input schemas and consistent error handling.
- **Idempotent schema**: `init_schema()` is safe to run on every startup.
- **Search quality**: Dual-pass FTS (tsvector + ILIKE) handles Thai/mixed-language content well.
- **Observability**: Health endpoints (liveness, readiness, full health), reconcile audit log, supersede audit log.

### Areas Needing Attention

| Priority | Issue | Recommendation |
|---|---|---|
| **P0** | 3 files >750 lines (`pg_store.py` 1005L, `line_handler.py` 822L, `routes.py` 792L) | Split per recommendations in Section 11.5 |
| **P1** | Duplicate OllamaEmbedder instantiation pattern (3 places) | Extract `create_embedder()` factory |
| **P1** | Duplicate RAG pattern (3 places: chat, LINE ask, LINE /ask) | Extract `src/retrieve/rag.py` |
| **P1** | Hardcoded DB credentials in `config.py` default | Remove default, require explicit `DATABASE_URL` |
| **P2** | Content-hash dedup uses 64-bit hash (collision risk at scale) | Upgrade to full SHA-256 or 128-bit truncated hash |
| **P2** | Hash dedup doesn't filter superseded documents | Add `AND superseded_by IS NULL` to dedup query |
| **P2** | No input sanitization or content size limits on push/search | Add content length limits, rate limiting |
| **P3** | `docker/.env` file may contain real secrets (gitignored, verify) | Run `git check-ignore docker/.env` to confirm |
| **P3** | Dead code: pending reviews CRUD, confirmation keywords | Either remove or document as "reserved for future use" |
| **P3** | SSRF risk in `/api/ingest/youtube` and `/api/ingest/website` | Add URL allowlisting or local-only validation |

---

> "ความรู้ไม่ใช่สิ่งที่เราเก็บ แต่มันคือสิ่งที่เราเชื่อมโยง" — Synapse Oracle

Generated: 2026-05-27 23:35 | Synapse v4.0.0
