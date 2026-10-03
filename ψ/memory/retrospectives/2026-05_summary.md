# Retrospectives — May 2026 Summary

> Consolidated from 11 session retros. Last updated: 2026-05-28.

## Week 1 (May 5-11)

### May 5 — Deep Learn + Bug Fix (1h 24m, 23 files)
- Ran `/learn --deep` with 5 parallel agents; uncovered QdrantStore.search() bug (accepted source_project/concepts params but never used them in filters)
- Fixed Dockerfile CMD, consolidated 3 duplicate fixture files into conftest, deleted 16 broken V1 test files, wrote Thai technical manual; 97 tests passing
- Friction: Python env mismatch (pip in .venv vs system python3); V1 code still in repo alongside src/ causing confusion

### May 6 — V3 Parity Feature Completion (16h, 20+ files)
- Built 8 remaining V3 features: project registry, cross-project search, search cache (LRU+TTL), config hot-reload, daemon lifecycle, health expansion, scheduled scanning, local-only enforcement
- Verified all 21 CLI commands, 18 API endpoints; 119 tests passing; wrote 12 technical manual MD files; added `cleanup` import fix for `_cmd_status` NameError
- Friction: 5 new modules (registry, cache, daemon, scheduler, local_only) had zero test coverage; context compaction destroyed continuity across marathon session

### May 7 — CLI PATH Fix + Project Onboarding (2h, 0 code changes)
- Fixed `synapse` not in PATH (pip installed into .venv, not system Python 3.13); registered and init-scanned 5 projects (emily, god-port, texty, myfam, magic-numbers)
- Vault grew from 1 doc to 562 docs across 8 scopes; cross-project search became genuinely useful with real data
- Friction: PATH problem was preventable — tested with `python3 -c` workaround instead of verifying actual binary in user's shell; test gap from previous retro still unaddressed

### May 9 — Auto-Ingest Hooks + Installer (1h 40m, 7 files)
- Implemented PostToolUse auto-ingest hook (detects brain paths) and PreToolUse context injection hook (reminds to use synapse_search); created `synapse install-hooks` CLI with marker-based idempotency
- Verified end-to-end: wrote file under ψ/ → hook fired → doc appeared in vault → search found it; 19 installer tests; vault re-init'd to 608 docs after silent wipe
- Friction: Stale PID file masked running daemon; vault went from 564 to 1 doc without anyone noticing (no health monitoring); two hook entries registered (old + new)

### May 9 — Hook Module Rename Fix (20 min, 1 file + config)
- User reported `ModuleNotFoundError: No module named 'synapse'` — hooks and MCP args pointed to old module path after `synapse/` → `src/` rename
- Fixed 3 locations in settings.json: deleted dead hook, fixed MCP server args, added `cd` for working directory; DB confirmed 708 docs across 6 scopes
- Lesson: Module renames must grep ALL references — config, hooks, MCP args, not just source code; two coexisting ingest hooks is a sign of incomplete migration

### May 9 — Hook Empty CLI Arg Fix (9h, 1 file)
- Root cause: `$CLAUDE_CODE_FILEPATH` env var was empty string, but `len(sys.argv) > 1` accepted it; handler failed with exit 1 on every Edit operation
- Changed no-file-path behavior from `sys.exit(1)` to `sys.exit(0)` (silent skip for non-blocking additive hooks); 153 tests passing; added regression tests
- Lesson: Shell env vars passed as CLI args can be empty strings, not just absent; always validate string content, not just presence

### May 10 — Docker Migration + Production Deploy (6h 30m, 4 files)
- First real production deployment: created synapse database on infra-oracle PostgreSQL, applied schema, indexed 38 files; migrated from native daemon to Docker container
- Fixed Dockerfile build (missing README.md for hatchling metadata), added synapse service to shared docker-compose; health check confirmed: pg ok, qdrant ok, embedding ok
- Friction: Tests 151 passed but database didn't exist — should have run `synapse status` as merge validation; `pip install .` with hatchling requires all referenced files in build context

## Week 2 (May 12-18)

### May 14 — Pipeline Fixes + Deep Learning (7h, 12 files)
- Fixed 4 pipeline issues: JSON encoding with ensure_ascii for Thai, link resolution over-matching (exact first, ILIKE fallback), concepts dead (0 for all docs), chat API sources not rendering
- Created `src/ingest/concepts.py` (hashtag extraction), wired into push and init_scan; ran `/learn --deep` generating 136KB across 6 files; 159 tests passing
- Friction: Docker build context confusion wasted 10 min; concepts bug was a missing feature entirely, not a logic error; frontend re-render needed explicit setState call

### May 17 — Topic Monitor + Daemon Reliability (5h, 15 files)
- Built topic monitoring system: search_topics table, WebSearch (Serper/Tavily/DuckDuckGo) + SocialSearch (Twitter/Reddit/HN) connectors, hourly scheduler, 4 CLI commands
- Added reconcile_log table for persistent audit trail; fixed 3 daemon reliability bugs: Ollama boot crash (try/except), missing PID file, no shutdown cleanup; 192 tests (+33)
- Lesson: stdout is not logging — scheduled jobs need structured persistent logs in the database; daemon boot must be resilient to external service failures

## Week 3 (May 19-25)

No retrospectives recorded.

## Week 4 (May 26-28)

### May 27 — V4: PostgreSQL Single Source of Truth (15h, 46 files total across full migration)
- Replaced Qdrant with pgvector — removed ~3500 lines of dual-store complexity (QdrantStore, hook_handler, dual-write logic); architecture: one SQL call for hybrid search
- Fixed 6 runtime bugs: DISTINCT+ORDER BY incompatibility, asyncpg vector encoding, content_hash generation, doc_type validation, search_fts tags, source formatting; centralized 8 duplicate source formatting blocks into 2 helper functions
- Lesson: EXISTS subquery beats DISTINCT+JOIN for tag-filtered vector search; mock-heavy tests missed real pgvector type-mapping bugs; integration tests with real database are essential

### May 28 — Tag Search Fix + Docker Logging (8h 23m, 4 files + tests)
- Fixed tags showing as `[]` in all search results: tags stored in both JSONB column AND junction table, but 3 read paths (search_similar, RRF fusion, list_docs) skipped enrichment
- Added tag enrichment to search_similar() via junction table batch query; fixed reciprocal_rank_fusion to merge tags instead of first-write-wins; 567 tests passing
- Added dedicated StreamHandler to LINE handler (uvicorn overrides basicConfig); verified Docker bind mount persistence across restarts

## Patterns Across May

- **Test coverage persistently lagging** — flagged in 4 retros (May 5, 6, 7, 14) with 5 new modules having zero tests for weeks; resolved in May 28 push to 567 tests
- **Hook/config drift after structural refactors** — module rename `synapse/` → `src/` left stale references twice (May 9 retros); settings.json and MCP args not updated atomically with source
- **Logging and observability gaps** — recurring theme: no reconcile history (May 17), no vault health monitoring (May 9), Docker logging broken by uvicorn (May 28); all fixed reactively
- **Dual-storage complexity is a root cause** — Qdrant+PostgreSQL dual-write created ~3500 lines of sync logic (removed in v4); JSONB+junction table dual storage caused tag search bugs (May 28)
- **Production deployment catches what tests miss** — database didn't exist (May 10), Dockerfile broken (May 10, 14), real pgvector exposed mock-hidden type-mapping bugs (May 27)
- **No commits for 10 of 11 sessions** — every retro from May 5-27 reports "0 commits" or "uncommitted changes"; only May 28 broke the pattern with 5 commits; giant uncommitted diff was a recurring risk
- **Progressive simplification** — architecture evolved from 3-layer (SQLite+ChromaDB) → 2-layer (PG+Qdrant) → 1-layer (PG+pgvector); each step removed complexity and failure modes
