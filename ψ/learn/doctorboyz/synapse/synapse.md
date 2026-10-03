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

**Key insights**:
1. Hashtag concept extraction (`#concept-name`) now auto-populates concepts table on every push
2. Chat sources now render immediately in frontend via `setMessages` callback in `onSources`
3. Lifecycle tests fixed by patching `src.registry.restore_registry_backup` with `AsyncMock`
4. Full test suite: **159 passed, 0 failed**
5. UX audit found critical accessibility gaps: GraphView nodes lack `role`/`tabIndex`, search has no debounce, CommandsPage hardcodes dark palette