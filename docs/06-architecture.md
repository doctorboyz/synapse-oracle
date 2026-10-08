# Synapse Knowledge Architecture

> Agent-first knowledge service for the Oracle ecosystem.
> Hybrid Knowledge Framework — PostgreSQL + Qdrant + Ollama.

---

## 1. Knowledge Sources (6 Ingestion Paths)

Every piece of knowledge enters through one of these doors, all converging on `Push.push_text()`.

| Source | Trigger | File |
|--------|---------|------|
| **CLI Manual Push** | `synapse push --title "..." --content "..."` or `synapse push --file path.md` | `src/ingest/push.py` |
| **File Scan (Init)** | `synapse init --path . --scope my-project` | `src/ingest/init_scan.py` |
| **Oracle Auto-Ingest** | Claude Code `PostToolUse` hook on `κ/` or `ψ/` files | `src/ingest/hook_handler.py` |
| **MCP Tools** | Agent calls `synapse_push` via stdio MCP | `src/mcp/server.py` |
| **HTTP API / Webhook** | `POST /api/push`, `POST /api/webhook` | `src/api/routes.py` |
| **External Ingest** | `POST /api/ingest/{youtube,website,file}` | `src/api/routes.py` |

### Source Details

**Init Scan** walks directories recursively, reading `.md`, `.txt`, `.rst`, `.pdf`, `.docx`. Skips `{.git, node_modules, __pycache__, .venv, ...}`. Extracts oracle metadata automatically (doc_type, oracle_name, brain_tier, scope). Content over 2000 chars gets LLM-summarized before storage.

**Oracle Hook** fires on every `Write`/`Edit` tool use. Filters only paths under `κ/` or `ψ/` (brain structure). Reads `CLAUDE_CODE_FILEPATH` from environment. Auto-detects scope from git root + `CLAUDE.md`.

---

## 2. Processing Pipeline

All sources flow through the same pipeline in `Push.push_text()` (`src/ingest/push.py`):

```
ingest → validate → summarize → dedup → store → trace → embed
```

### Step 1: Validation
`validate_doc_type()` checks against `VALID_DOC_TYPES`: `learning, pattern, retro, reference, handoff, protocol, wisdom, instinct, log, note`.

### Step 2: Summarization (Conditional)
If `len(content) > 3000` and Ollama is available:
- Model: `kimi-k2.6:cloud` (configurable)
- Endpoint: `POST /api/chat` at `OLLAMA_URL`
- Temperature: `0.3`
- System prompt: "concise knowledge summarizer... 3-5 sentences"
- On failure: falls back to `content[:2000]`

### Step 3: Deduplication
`PgStore.add()` computes `content_hash = sha256(content)[:16]`.
Unique constraint on `(content_hash, scope)`. Duplicates return `{"status": "duplicate"}`.

### Step 4: PostgreSQL Storage
Inserts into `knowledge_documents` with:
- Core: `title, content, content_hash, scope, doc_type`
- Provenance: `source_file, source_type, source_project`
- Oracle-aware: `oracle_name, brain_path, brain_tier`
- Structured: `concepts (JSONB), tags (JSONB), summary`
- Auto-updates `scope_registry.doc_count`
- Populates `concepts` table + `document_concepts` junction

### Step 5: Obsidian Link Tracing
`create_traces_from_links()` parses `[[Target]]` and `[[Target|Display]]` syntax.
Resolution priority:
1. Exact title match across all scopes (`ILIKE`)
2. `source_file` path match (for path-based links like `[[2026-05-06/2247_ARCHITECTURE]]`)
3. Exact title in same scope
4. FTS fallback across all scopes

Creates `trace` rows with `relation="references"`, `confidence=0.9`.

### Step 6: Vector Embedding
If `embed=True` and Qdrant + Embedder available:
- Embedding text = `summary or content`
- Model: `nomic-embed-text` (configurable via `EMBEDDING_MODEL`)
- Dimension: `768` (configurable via `EMBEDDING_DIM`)
- Upsert to Qdrant collection `synapse_vectors` with payload: `{title, scope, doc_type, superseded, oracle_name, brain_tier, concepts}`
- On failure: status = `"indexed_pg_only"`

---

## 3. Reconciliation (Maintenance)

| Operation | File | What It Does |
|-----------|------|--------------|
| **Defrag** | `src/reconcile/defrag.py` | Groups by `(title, scope)`. Supersedes duplicates with reason `"defrag_duplicate"`. |
| **Detox** | `src/reconcile/detox.py` | Pairs same-scope, same-type docs. LLM judge chain (gemma4:cloud → glm-5.3-flash:cloud → glm-5.3:cloud) analyzes conflicts via structured JSON output. Supersedes with merged content if conflict confirmed. |
| **Scheduled** | `src/scheduler.py` | Background daemon runs scan every `SYNAPSE_SCAN_INTERVAL` seconds and reconcile at `SYNAPSE_RECONCILE_HOUR` (default 02:00). |

---

## 4. Query Methods

### 4.1 Hybrid Search (`src/retrieve/hybrid_search.py`)

| Mode | Behavior | Fallback |
|------|----------|----------|
| `hybrid` (default) | Dense + FTS → RRF fusion | FTS-only if Qdrant down |
| `dense` | Qdrant vector search only | Error if missing |
| `fts` | PostgreSQL `tsvector` only | None |

**RRF Parameters:**
- Weights: `[0.6, 0.4]` (dense, fts) — configurable via `SEARCH_WEIGHTS`
- Constant `k = 60` — configurable via `search_rrf_k`
- Formula: `score = weight / (k + rank)`
- Cache layer: LRU + TTL (`CACHE_TTL=300s`, `CACHE_MAX_SIZE=1000`)

**Cross-Scope Search:**
- `search_cross_scope(query, scopes, limit, mode)`
- Runs per-scope search, merges via RRF with equal weights
- Ensures fairness across scopes (prevents large scopes from drowning small ones)

### 4.2 PostgreSQL Queries (`src/db/pg_store.py`)

| Method | SQL | Filters |
|--------|-----|---------|
| `search_fts()` | `to_tsquery('english', $1)` on `search_vector` GIN index | scope, doc_type, oracle, source_project |
| `get()` | PK lookup + optional supersession chain walk | — |
| `list_docs()` | `ORDER BY created_at DESC/ASC`, `LEFT(content, 500)` | scope, doc_type, oracle |
| `list_concepts()` | `LEFT JOIN` + `GROUP BY` + `COUNT` | ILIKE search on name |
| `get_trace_chain()` | BFS walk on `trace` table | direction, max_depth, relation |
| `stats()` | Aggregate counts | by type, scope, oracle |

### 4.3 HTTP API Endpoints (`src/api/routes.py`)

| Endpoint | What It Does |
|----------|--------------|
| `POST /api/search` | Hybrid/dense/fts search |
| `POST /api/search-cross` | Cross-scope search |
| `GET /api/trace/{doc_id}` | Trace chain (upstream/downstream/both) |
| `POST /api/chat` | Search → fetch context → stream Ollama response with citations |
| `POST /api/resolve-links` | Resolve `[[Link]]` targets to document IDs |

### 4.4 Trace Chain

`get_trace_chain(doc_id, direction, max_depth, relation)` performs BFS on the `trace` table:
- `upstream`: follow `target_id` → `source_id` (who references this doc)
- `downstream`: follow `source_id` → `target_id` (what this doc references)
- `both`: combine both directions
- Default `max_depth=5`
- Optional `relation` filter

---

## 5. Data Storage

### PostgreSQL Schema (`src/db/schema.sql`)

**Tables:**

| Table | Purpose |
|-------|---------|
| `knowledge_documents` | Primary store — documents with full content, metadata, tsvector |
| `supersede_log` | Audit trail of all supersession events |
| `scope_registry` | Scope metadata + document counts |
| `concepts` | Concept catalog with descriptions |
| `document_concepts` | Many-to-many junction |
| `trace` | Document relationship graph edges |
| `registered_projects` | Cross-project search registry |

**Key Indexes:**
- `idx_doc_search` — GIN on `search_vector`
- `idx_doc_scope`, `idx_doc_type`, `idx_doc_oracle` — partial (active docs only)
- `idx_trace_source`, `idx_trace_target`

**Trigger:**
- `trg_search_vector` — auto-computes `tsvector` from `title`(A), `content`(B), `concepts`(C) on insert/update.

### Qdrant (`src/db/qdrant_store.py`)

- Collection: `synapse_vectors`
- Vector: `size=768`, `distance=COSINE`
- Payload: `{title, scope, doc_type, superseded, oracle_name, brain_tier, concepts}`
- Auto-created on first connect
- Superseded docs marked via `set_payload(superseded=True)` — excluded from search

---

## 6. Configuration

Key environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` / `SYNAPSE_DB_URL` | `postgresql://admin:88888888@localhost:5432/synapse` | PostgreSQL |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama LLM + embedding |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model |
| `EMBEDDING_DIM` | `768` | Vector dimension |
| `SEARCH_WEIGHTS` | `0.6,0.4` | Hybrid RRF weights |
| `CACHE_TTL` | `300` | Search cache TTL (seconds) |
| `CACHE_MAX_SIZE` | `1000` | Cache max entries |
| `SYNAPSE_SCAN_INTERVAL` | `0` (disabled) | Background scan interval |
| `SYNAPSE_RECONCILE_HOUR` | `2` | Daily reconcile hour |

---

## 7. Architecture Flow

```
Ingestion (6 paths)
  ├─ CLI: synapse push / synapse init
  ├─ Hook: PostToolUse on κ/ψ files
  ├─ MCP: synapse_push tool
  ├─ API: /api/push, /api/webhook, /api/ingest/*
  └─ All → Push.push_text()

Pipeline
  ├─ validate_doc_type()
  ├─ _summarize() (>3000 chars → Ollama)
  ├─ PgStore.add() (dedup by content_hash+scope)
  ├─ create_traces_from_links() ([[Link]] → trace)
  └─ QdrantStore.upsert() (embed → vector store)

Storage
  ├─ PostgreSQL: docs, FTS, concepts, traces, scopes, supersede_log
  └─ Qdrant: vectors + payload filters

Retrieval
  ├─ hybrid:  RRF(0.6 dense + 0.4 fts), k=60
  ├─ dense:   Qdrant vector only
  ├─ fts:     PostgreSQL tsvector only
  ├─ cross:   per-scope → RRF merge
  └─ trace:   BFS walk (upstream/downstream/both, depth 5)

Maintenance
  ├─ defrag:  supersede duplicates
  └─ detox:   LLM conflict detection + merge
```

---

## 8. MCP Tools (14 total)

`synapse_search`, `synapse_push`, `synapse_supersede`, `synapse_trace`, `synapse_trace_chain`, `synapse_concepts`, `synapse_get`, `synapse_scope`, `synapse_stats`, `synapse_list`, `synapse_register`, `synapse_unregister`, `synapse_projects`, `synapse_search_cross`

---

*Generated: 2026-05-14*
*Version: Synapse v3*
