# Synapse v4 — Code Quality Analysis

## Dead Code

| Item | Location | Issue |
|------|----------|-------|
| CONFIRM_* constants | line_handler.py:19-21 | v3 confirmation flow, never used |
| _is_question() | line_handler.py:120 | Defined but never called in v4 |
| SearchRequest class | routes.py:45-58 | Defined but never instantiated |
| cli_command decorator | cli.py:72-89 | Defined but never used |
| detect_scope/validate_scope aliases | registry.py:36-37,93 | Deprecated wrappers |
| --scope argument | main.py (5 subcommands) | Marked deprecated, still processed |
| scope_registry table | schema.sql:71 | No longer populated in v4 |
| summarize_with_llm() | init_scan.py:97 | Defined but not called by init_scan() |
| summarize_content() | reconcile/llm.py:94 | Not called by reconcile pipeline |
| Stale version | __init__.py:2 | `__version__ = "3.0.0"` should be "4.0.0" |

## Correctness Issues

### HIGH Severity
1. **SQL injection in _trace_walk()** (pg_store.py:504): `f" AND t.relation = '{relation}'"` — string interpolation
2. **NameError: undefined `io` module** (routes.py:491): `io.BytesIO(data)` but `io` never imported
3. **AttributeError on embedder=None** (routes.py:639,545,720): `embedder.settings` accessed without None check
4. **Undefined variable `skipped`** (line_handler.py:713): Incremented but never initialized

### MEDIUM Severity
5. **Migration script crash** (scope_to_tags.py:108,120): Calls `pg.start()`/`pg.stop()` which don't exist
6. **get() chain bug** (pg_store.py:143): Only follows 1 level of supersession
7. **Race condition** (tests/conftest.py:22): `_schema_initialized` not guarded by lock
8. **LINE /stats label bug** (line_handler.py:372): Reports "Tags ทั้งหมด" but shows scope count
9. **event_to_scope() still called** (line_handler.py:519): v3 function with unused result

## Best Practice Violations

### Global Mutable State
- routes.py:19-23 — `pg`, `embedder`, `push`, `search`, `_settings` as module globals
- main.py:19-20 — `_pg`, `_scheduler`
- topic_monitor.py:17 — `_seen_urls: set[str]`

### Bare except Exception: (16 occurrences)
- ollama.py:60, init_scan.py:150, obsidian_links.py:74,89,114
- cli.py:46, mcp/server.py:244, line_handler.py:749
- routes.py:243,264,345,498,507,733, main.py:67, detox.py:99

### Other Issues
- **Lazy imports**: 20+ occurrences of runtime imports inside functions
- **Settings dataclass too large**: 30+ fields, fragile reload() via vars()
- **No input validation**: POST endpoints use raw dict access → KeyError on missing fields
- **No request body size limits**: Large payloads could exhaust memory
- **No rate limiting**: All endpoints open
- **Default DB URL hardcodes credentials**: `admin:88888888` in config.py:18

## File Organization

### Files Over 800 Lines
| File | Lines | Recommendation |
|------|-------|---------------|
| pg_store.py | 1006 | Split: pg_crud, pg_search, pg_vector, pg_concepts, pg_trace, pg_chunks |
| line_handler.py | 823 | Split: commands, knowledge_builder, media, formatting |
| routes.py | 793 | Split: routes_search, routes_push, routes_ingest, routes_obsidian |

### Duplicate Logic
1. **Summarization** ×3: init_scan.py, reconcile/llm.py, openrouter_client.py — consolidate
2. **Search + answer pattern** ×2: line_handler.py _answer_question + /ask handler — extract to shared RAG module
3. **Component initialization** ×3: main.py startup, cli.py get_components(), mcp/server.py create_app() — extract bootstrap.py
4. **RRF implementation** ×2: hybrid_search.py + pg_store.py internal merge — consolidate
5. **_ensure_list()** ×3: pg_store.py, push.py, routes.py inline — extract to utils.py

### Code in Wrong Place
- reconcile/llm.py summarization → should be in src/llm/
- init_scan.py file readers → duplicate of routes.py parse_file_content → consolidate
- main.py CLI commands (640 lines) → should be in cli.py
- routes.py _extract_youtube_id → should be in ingest/youtube.py

## Testing Gaps

### What's NOT Tested
1. openrouter_client.py — No test file (OCR, chat, summarize)
2. connectors/web_search.py — No tests
3. connectors/social_search.py — No tests
4. connectors/topic_monitor.py — No tests
5. migrate/scope_to_tags.py — No test file
6. Streaming /api/chat — Not tested
7. File upload endpoints — Not tested
8. Error paths — Almost no error behavior tests
9. Dense/vector search — embedder=None in all tests
10. reconcile/__init__.py orchestrator — No direct test

## Prioritized Action Items

| Priority | Issue | Risk |
|----------|-------|------|
| HIGH | SQL injection in _trace_walk() | Data leakage/DB corruption |
| HIGH | NameError on io module | Crash on file upload |
| HIGH | AttributeError on embedder=None | Crash in chat/suggest-tags |
| HIGH | Undefined skipped variable | Crash on sticker events |
| MEDIUM | Migration script crash | Broken migration |
| MEDIUM | No auth on API endpoints | Unauthenticated access |
| MEDIUM | Hardcoded DB password default | Credential exposure |
| MEDIUM | Missing tests for OpenRouter | Untested critical path |
| LOW | Dead CONFIRM_* constants | Code bloat |
| LOW | 16 bare except blocks | Silent error swallowing |
