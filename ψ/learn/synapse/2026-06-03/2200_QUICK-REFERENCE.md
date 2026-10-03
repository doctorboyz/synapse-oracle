# Synapse v4 — Quick Reference (2026-06-03)

## Config (env vars → YAML hot-reload)

| Var | Default | Purpose |
|-----|---------|---------|
| DATABASE_URL | postgresql://admin:88888888@localhost:5432/synapse | PG connection |
| OLLAMA_URL | http://localhost:11434 | Ollama endpoint |
| EMBEDDING_MODEL | nomic-embed-text | Embedding model |
| EMBEDDING_DIM | 768 | Vector dimensions |
| SYNAPSE_HOST | 0.0.0.0 | API bind host |
| SYNAPSE_PORT | 8420 | API port |
| SEARCH_WEIGHTS | 0.6,0.4 | Dense/FTS RRF weights |
| CACHE_TTL | 300 | Search cache TTL (seconds) |
| CACHE_MAX_SIZE | 1000 | Max cached queries |
| SYNAPSE_SCAN_INTERVAL | 0 | Background scan interval (0=off) |
| SYNAPSE_RECONCILE_HOUR | 2 | Nightly reconcile hour |
| SYNAPSE_TOPIC_INTERVAL | 3600 | Topic monitor interval (0=off) |
| OBSIDIAN_VAULT_PATH | "" | Obsidian vault root |
| OPENROUTER_API_KEY | "" | OpenRouter API key |
| OPENROUTER_MODEL | google/gemini-2.0-flash-001 | LLM model |
| OPENROUTER_SUMMARY_MODEL | deepseek/deepseek-chat-v3-0324 | Summary model |
| LINE_CHANNEL_SECRET | "" | LINE webhook verification |
| LINE_CHANNEL_ACCESS_TOKEN | "" | LINE push messages |
| SERPER_API_KEY | "" | Web search (Serper) |
| TAVILY_API_KEY | "" | Web search (Tavily) |

## Key File Sizes

| File | Lines | Purpose |
|------|-------|---------|
| pg_store.py | 1342 | PostgreSQL CRUD + FTS + vector + all queries |
| line_handler.py | 1170 | LINE webhook processing |
| main.py | 743 | FastAPI app + CLI dispatcher |
| routes.py | 792 | HTTP API endpoints |
| mcp/server.py | 484 | MCP stdio server (15 tools) |
| scheduler.py | 313 | Background tasks (scan, reconcile, monitor, alerts) |
| detox.py | 240 | LLM conflict detection |
| defrag.py | 205 | Duplicate compaction |
| init_scan.py | 200 | Directory scanning |
| daemon.py | 199 | PID/signal/Docker lifecycle |
| push.py | 267 | Ingest pipeline |
| hybrid_search.py | 158 | RRF fusion search |
| registry.py | 161 | Project registration |
| config.py | 145 | Settings (env + YAML) |
| tag_rules.py | 140 | Tag rule engine |
| obsidian_links.py | 120 | [[Link]] parser + trace creation |
| obsidian_writer.py | 140 | Write .md to vault |
| web_search.py | 150 | Serper/Tavily/DuckDuckGo |
| social_search.py | 150 | Twitter/Reddit/HN |
| openrouter_client.py | ~180 | OpenRouter + Ollama fallback |
| cli.py | 88 | Shared async setup/teardown |

## Total: ~16,677 lines src + ~7,523 lines tests = ~24,200 lines Python

## Tests (34 files)

test_pg_store, test_qdrant_store (removed?), test_hybrid_search, test_api_routes, test_mcp_server, test_hook_handler (→test_claude_ingest), test_cli, test_push, test_concepts, test_oracle_paths, test_obsidian_links, test_obsidian_writer, test_cache, test_config, test_daemon, test_embed, test_hooks_installer, test_init_scan, test_lifecycle, test_line_handler, test_line_handler_v2, test_local_only, test_reconcile_defrag, test_reconcile_detox, test_reconcile_llm, test_registry, test_scheduler, test_tag_rules, test_assistant_scheduler, test_connectors, test_guided_questions, test_openrouter_client, test_webhook_verify, test_vault_migrator

## Architecture Decisions (v4)

1. **Single store (PostgreSQL + pgvector)** — Removed Qdrant entirely. ~3,500 lines of dual-store complexity eliminated.
2. **Tags over scope** — scope column deprecated, tags via junction table. Scope still works but tags are primary.
3. **SQL hybrid_search function** — Native PostgreSQL function for combined dense+FTS with tag filtering via EXISTS subquery.
4. **Chunking for long docs** — Documents > 1500 chars auto-chunked with 200-char overlap, each chunk embedded separately.
5. **Semantic dedup on push** — Before storing, check pgvector similarity ≥ 0.85 threshold.
6. **OpenRouter as primary LLM** — Ollama as fallback for summarization and OCR.
7. **LINE as primary input channel** — Full auto-ingest pipeline with OCR, Q&A, commands, tag rules.
8. **Tag rules engine** — Auto-classify task/reminder/event → scheduled_tasks → LINE alerts.
9. **Obsidian bidirectional** — Read from vault (init_scan), write to vault (obsidian_writer), link via [[wikilinks]] → traces.
10. **Config hot-reload** — SIGHUP triggers Settings.from_yaml() reload without restart.

## Known Issues & Debt (from retros)

- **No CI** — Tests pass locally but no automated pipeline. Hidden failures accumulate.
- **main.py is 743 lines** — CLI dispatcher should be split into separate command modules.
- **pg_store.py is 1342 lines** — Should be split: CRUD, search, tags/concepts, traces, scheduled tasks, etc.
- **line_handler.py is 1170 lines** — Message processing should be modularized.
- **No commits pattern** — 10 of 11 sessions in May had 0 commits. Giant uncommitted diffs are a recurring risk.
- **Tests cover happy paths well** — Edge cases (concurrent access, large content, network failures) less covered.
