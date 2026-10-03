# Synapse v4 — Application Logic Analysis

## Use Cases

### LINE Chatbot
- `/ask <question>` — Cross-scope hybrid search + LLM answer with citations
- `/search <query>` — FTS across all documents with formatted results
- Auto-ingest — All non-sticker text >10 chars auto-stored, dedup-checked, embedded
- Image OCR — OpenRouter vision (Gemini Flash) or Ollama fallback
- Task detection — Due dates, assignees, status, priority from text
- `/stats`, `/tags`, `/recent [scope]`, `/help`

### API Access (30+ endpoints)
- Push, search, hybrid search, cross-scope search
- Document CRUD, supersede, trace
- Ingest: YouTube, website, file upload
- Chat (streaming), suggest-tags, write-to-obsidian
- Health checks, reconcile log, search topics

### MCP Integration (18 tools)
- Full API surface via stdio for Claude Code
- synapse_search, synapse_push, synapse_write_to_obsidian, etc.

### CLI (26 subcommands)
- push, search, get, list, stats, tags, concepts
- supersede, trace, trace-chain
- init, reconcile, register, unregister, projects, scan
- serve, mcp, stop, status

## Key User Journeys

### LINE User Asks a Question
```
LINE: "/ask How does pgvector work?"
  → process_line_events()
  → _handle_command(cmd="ask", args="...")
  → pg.search_fts() (tsvector + ILIKE RRF merge)
  → Tag enrichment via document_tags JOIN
  → OpenRouterClient.chat() with context + question
  → Fallback: search results without LLM if OpenRouter unavailable
  → _format_source_line() for human-readable citations
  → _send_reply() via LINE API
```

### LINE Auto-Ingest
```
LINE: "Meeting notes: discussed K8s autoscaling"
  → Not a command, text >10 chars
  → _build_knowledge_doc(): title, scope, doc_type, tags, concepts
  → _extract_task_info(): check for due dates, @mentions, status
  → Push pipeline:
     → validate_doc_type → extract_concepts
     → semantic_dedup (skip for DMs, run for groups)
     → pg.add() → content_hash SHA256[:16] dedup
     → trace_links from [[wikilinks]]
     → embed → pg.set_embedding()
     → chunk (if >1500 chars)
  → Reply (DM only): "✅ บันทึกความรู้แล้ว"
```

### API Push Pipeline
```
POST /api/push {"title": "...", "content": "...", "tags": [...]}
  → validate_doc_type
  → extract_concepts
  → _semantic_dedup(): embed → pg.search_similar() → threshold 0.85
  → pg.add(): content_hash dedup → INSERT + tags + concepts
  → embed + set_embedding
  → chunk if >1500 chars
  → Return {id, status: "indexed"}
```

## Business Rules

### Nothing Is Deleted — Supersede Only
- Manual: CLI/API/MCP supersede
- Task auto-update: same title+tag → auto-supersede
- defrag: exact/semantic duplicates → supersede into canonical
- detox: conflicting docs → merge + supersede
- init_scan: content_hash change → supersede + re-index
- Process: fetch old → insert new → set old.superseded_by → clear old embedding

### Deduplication
- **Exact**: SHA256(content)[:16] hash match → reject
- **Semantic**: pgvector cosine similarity >= 0.85 → reject (skipped for DMs)
- **defrag Phase 1**: Group by content_hash → supersede all but newest
- **defrag Phase 2**: pgvector ANN, threshold 0.95

### Group/Room Silent Mode
- Groups: no confirmation replies, semantic dedup enabled
- DMs: confirmation replies, semantic dedup skipped (skip_semantic_dedup=True)

### Task Detection
- Due dates: Thai/ISO/relative formats
- Status: EN ("pending", "done") + TH ("รอ", "เสร็จแล้ว")
- Assignee: @username patterns
- Priority: urgent/ด่วน, high/สูง, medium/กลาง, low/ต่ำ

## Edge Cases

### Ollama Down (No Embeddings)
- Push: semantic dedup skipped, embedding skipped (warning), doc stored without vector
- Search: dense mode raises SearchError, hybrid falls back to FTS only
- Startup: log warning, continue with embedder=None

### OpenRouter Down (No LLM)
- LINE /ask: falls back to search results without LLM answer
- OCR: falls back to Ollama vision model
- Reconcile: marks conflicts "LLM unavailable", skips resolution

### Content Too Short
- LINE text <10 chars: _build_knowledge_doc() returns None, skipped

### Supersede on Already-Superseded
- pg.supersede() queries WHERE superseded_by IS NULL → ValueError if already superseded

### Chunking
- Content <=1500 chars: no chunks
- Content >1500 chars: split into 1500-char chunks with 200-char overlap
- Individual chunk embedding failures: logged as warnings, remaining chunks continue

## Testing Gaps

### Critical Untested Paths
1. `src/llm/openrouter_client.py` — No tests at all (OCR, chat, summarize)
2. `src/connectors/web_search.py` — No tests (Serper, Tavily, DuckDuckGo)
3. `src/connectors/social_search.py` — No tests (X, Reddit, HN)
4. Streaming `/api/chat` — Not tested
5. `/api/ingest/youtube`, `/api/ingest/website`, `/api/ingest/file` — Not tested
6. Full Push + Embed + Chunk pipeline — No end-to-end test
7. reconcile/__init__.py orchestrator — No dedicated test

### Test Quality
- All tests use real PostgreSQL (integration, not mocked DB)
- Embedder is always None in tests — no dense/vector path coverage
- No performance tests
- No E2E tests for LINE webhook integration
