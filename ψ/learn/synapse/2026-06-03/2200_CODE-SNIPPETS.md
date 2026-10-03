# Synapse v4 — Code Patterns & Snippets (2026-06-03)

## Component Initialization Pattern

All entry points follow: Settings → PgStore → connect → init_schema → OllamaEmbedder (optional) → Push/Search

```python
# Standard initialization (used in CLI, API startup, MCP)
settings = Settings()
pg = PgStore(settings)
await pg.connect()
await pg.init_schema()
embedder = None
try:
    embedder = OllamaEmbedder(settings)
except Exception:
    log.warning("Ollama not available, running without embeddings")
push = Push(pg, embedder)
search = HybridSearch(pg, embedder, settings.search_weights, settings.search_rrf_k)
```

## Search Weights Configuration

```python
# config.py — hybrid search weights
search_weights: list[float] = [0.6, 0.4]  # 60% dense, 40% FTS
search_rrf_k: int = 60  # RRF constant
```

## Tag Handling (Dual Storage)

Tags live in both JSONB column AND junction table. The JSONB column was migrated away (schema.sql drops it), but the pattern of enriching from the junction table is critical:

```python
# pg_store.py — tag enrichment after search
tags = (
    SELECT jsonb_agg(t.name) FROM document_tags dt 
    JOIN tags t ON t.id = dt.tag_id WHERE dt.doc_id = kd.id
)
```

Every read path must enrich tags from the junction table. Three bugs found and fixed in May 2026 where paths forgot enrichment.

## Semantic Dedup Pattern

```python
# push.py — before storing
if not skip_semantic_dedup:
    dup_result = await self._semantic_dedup(content, tags)
    if dup_result:
        return dup_result  # {"status": "semantic_duplicate", "id": ..., "similarity_score": ...}
```

## Supersede Pattern (Nothing is Deleted)

```python
# pg_store.py — creates new doc, marks old as superseded
await pg.supersede(old_id=old_id, new_content=content, reason="updated")
# → old doc: superseded_by = new_id
# → new doc: fresh UUID, created_at = now()
# → supersede_log: old_id, new_id, reason, timestamp
```

## Obsidian Bidirectional Integration

```python
# obsidian_writer.py — write doc to vault with YAML frontmatter + [[wikilinks]]
frontmatter = _build_frontmatter(doc)  # tags, concepts, source, doc_id, etc.
body = f"# {title}\n\n{content}\n\n## Related Notes\n\n{related_section}"
# → writes .md file to vault path

# obsidian_links.py — parse [[links]] from content and create traces
links = extract_links(content)  # regex: \[\[([^\]|]+)(?:\|([^\]]+))?\]\]
resolved = await resolve_links(pg, links, tags=tags, exclude_id=doc_id)
await create_traces_from_links(pg, doc_id, content, tags=tags)
```

## Chunking for Long Documents

```python
# push.py — documents > 1500 chars get chunked
CHUNK_SIZE = 1500  # chars per chunk
CHUNK_OVERLAP = 200  # chars overlap
chunks = self.chunk_text(content)
for i, chunk_text in enumerate(chunks):
    chunk_id = await self.pg.add_chunk(doc_id, i, chunk_text)
    vector = await self.embedder.embed(chunk_text[:MAX_CHUNK_CHARS])
    await self.pg.set_chunk_embedding(chunk_id, vector)
```

## LINE Message Processing Flow

```
incoming LINE event
  → verify signature (HMAC-SHA256)
  → detect message type (text/image/video/audio/file/location)
  → if image/video: OCR via OpenRouter vision model
  → detect: slash command? question? task? regular text?
  → classify doc_type (knowledge/note/todo/reminder/event/payment)
  → extract tags (oracle tags + content tags + LINE context tags)
  → semantic dedup check (DM only)
  → push to vault
  → apply tag rules (auto-create scheduled tasks)
  → reply confirmation
```

## API Endpoints (25+)

| Method | Path | Purpose |
|--------|------|---------|
| POST | /api/search | Hybrid search |
| POST | /api/push | Add knowledge |
| POST | /api/webhook | Webhook push (with HMAC verify) |
| POST | /api/line-webhook | LINE message processing |
| POST | /api/supersede | Supersede document |
| POST | /api/trace | Create trace link |
| GET | /api/get/{doc_id} | Get document |
| GET | /api/list | List documents |
| GET | /api/scopes | List scopes |
| GET | /api/tags | List tags |
| GET | /api/concepts | List concepts |
| GET | /api/stats | Vault statistics |
| POST | /api/init | Scan directory |
| POST | /api/reconcile | Run reconciliation |
| POST | /api/register | Register project |
| POST | /api/unregister | Unregister project |
| GET | /api/projects | List registered projects |
| POST | /api/search-cross | Cross-scope search |
| GET | /api/health | Quick health check |
| GET | /api/health/live | Liveness |
| GET | /api/health/ready | Readiness (PG + embedder) |
| POST | /api/write-to-obsidian | Write docs to Obsidian vault |
| GET | /api/models | List Ollama models |
| POST | /api/chat | Streaming LLM chat with context |
| POST | /api/search-topics | Add/list search topics |
| GET | /api/reconcile-log | List reconcile runs |
| GET | /api/line-qr | LINE bot QR code |

## MCP Tools (15)

synapse_search, synapse_push, synapse_supersede, synapse_trace, synapse_trace_chain, synapse_concepts, synapse_get, synapse_scope, synapse_stats, synapse_list, synapse_register, synapse_unregister, synapse_projects, synapse_search_cross, synapse_write_to_obsidian, synapse_ingest_session, synapse_reconcile_log

## CLI Commands (25+)

serve, mcp, push, search, get, list, scope, tags, stats, supersede, trace, trace-chain, concepts, init, reconcile, register, unregister, projects, search-cross, stop, status, scan, install-hooks, topic-add, topic-list, topic-remove, topic-run

## Graceful Degradation Pattern

Ollama unavailable → embedder = None → FTS-only search, no vector search, no semantic dedup
Qdrant removed (v4) → all vectors in pgvector, single store
OpenRouter unavailable → fallback to Ollama qwen2.5:7b for summarization/OCR
