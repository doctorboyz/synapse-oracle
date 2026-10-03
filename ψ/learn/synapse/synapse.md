# Synapse Learning Index

## Source
- **Origin**: ./origin/
- **GitHub**: https://github.com/doctorboyz/synapse

## Explorations

### 2026-05-14 1503 (deep)
- [2026-05-14/1503_ARCHITECTURE.md|Architecture]
- [2026-05-14/1503_CODE-SNIPPETS.md|Code Snippets]
- [2026-05-14/1503_QUICK-REFERENCE.md|Quick Reference]
- [2026-05-14/1503_TESTING.md|Testing]
- [2026-05-14/1503_API-SURFACE.md|API Surface]
- [2026-05-14/1503_UXUI-REFERENCE.md|UX/UI Reference]

**Key insights (v3)**:
1. Hashtag concept extraction auto-populates concepts table on every push
2. Chat sources render immediately in frontend via `setMessages` callback
3. Lifecycle tests fixed by patching `src.registry.restore_registry_backup`
4. Full test suite: 159 passed, 0 failed
5. UX audit found critical accessibility gaps

### 2026-05-27 2335 (deep, v4 migration)
- [2026-05-27/2335_ARCHITECTURE.md|Architecture (v4)]
- [2026-05-27/2335_APP-LOGIC.md|App Logic]
- [2026-05-27/2335_CODE-ANALYSIS.md|Code Analysis]
- [2026-05-27/2335_QUICK-REFERENCE.md|Quick Reference]
- [2026-05-27/2335_UXUI-REFERENCE.md|UX/UI Reference]

**Key insights (v4 migration)**:
1. Qdrant removed entirely — pgvector is the only vector store
2. EXISTS subquery pattern for tag-filtered vector search
3. asyncpg requires manual vector encoding: `'[x,y,z]':vector`
4. 567 tests passing after tag enrichment fixes

### 2026-06-03 2200 (deep, fresh learn from source)
- [2026-06-03/2200_ARCHITECTURE.md|Architecture (v4 current)]
- [2026-06-03/2200_CODE-SNIPPETS.md|Code Patterns & Snippets]
- [2026-06-03/2200_QUICK-REFERENCE.md|Quick Reference]
- [2026-06-03/2200_TESTING.md|Testing Reference]
- [2026-06-03/2200_API-SURFACE.md|API Surface]

**Key insights (v4 current state)**:
1. 16,677 lines Python src + 7,523 lines tests = ~24,200 total
2. 44 source modules across 12 packages
3. pg_store.py (1342 lines) and line_handler.py (1170 lines) are the largest files — debt candidates for splitting
4. Tag-based assistant infrastructure: tag_rules + scheduled_tasks + alert_log + LINE push
5. OpenRouter primary LLM with Ollama fallback for summarization/OCR
6. Document chunking (>1500 chars) with 200-char overlap, each chunk embedded
7. Semantic dedup on push (≥0.85 similarity threshold)
8. LINE integration: full auto-ingest pipeline with OCR, Q&A, commands
9. Web/social search connectors: Serper, Tavily, DuckDuckGo, Twitter, Reddit, HN
10. 25+ HTTP endpoints, 15 MCP tools, 25+ CLI commands
