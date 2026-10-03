# Learnings — May 2026 Summary

> Consolidated from 14 individual lessons. Last updated: 2026-05-28.

## Testing & Quality

- **[2026-05-05] Mock tests catch hidden bugs**: When external services (Qdrant, Ollama) are always `None` in tests, their code paths are never exercised. Write mock tests that call methods with controlled inputs using the full parameter signature.
- **[2026-05-05] Consolidate fixtures into conftest.py**: When 2+ test files duplicate the same fixtures, consolidating into conftest.py breaks the duplication cycle and makes adding new test types trivial. Add convenience fixtures that compose simpler ones.
- **[2026-05-05] No CI = hidden test failures**: 16 V1 test files were broken with zero visibility after fixture removal. Without CI, broken tests don't block merges and the gap between "total files" and "passing tests" grows silently.
- **[2026-05-06] Manual verification is debt**: Manual testing proves features work NOW; tests prove they work FOREVER. Every new module MUST have a corresponding test file before marking the task complete. Run `pytest --cov=src --cov-report=term-missing`.
- **[2026-05-07] Test the product, not just the code**: `python3 -c "from src.main import cli_main"` tests the code but not the `synapse` binary users actually run. After `pip install -e .`, verify: `which synapse && synapse --help`. If you need a workaround to test, the normal path is broken.

## Tooling & Infrastructure

- **[2026-05-06] Linting catches NameErrors instantly**: A copy-paste import (`from src.cli import get_components, output`) failed at runtime because `cleanup` wasn't imported. ruff/pyflakes would flag this instantly. Add ruff to dev dependencies and CI.
- **[2026-05-09] Hook installation must be idempotent and marker-based**: Use marker strings embedded in hook commands as identity keys (e.g., `src.ingest.hook_handler`), not exact-match comparison. Survives timeout/matcher/arg changes and never reorders existing hooks.
- **[2026-05-09] Bash beats Python for PreToolUse context injection**: PreToolUse hooks fire hundreds of times per session. Python startup adds ~200ms per invocation; a bash `kill -0` PID check runs in ~5ms — 40x improvement. Use Python only when DB access is needed.
- **[2026-05-09] Vault data disappears silently on DB restart**: PostgreSQL restart or test teardown wipes the vault without notification. Always re-run `synapse init` after DB recreation. Consider a `synapse health` command that compares doc count against baseline.
- **[2026-05-09] Empty CLI args are not "missing"**: Shell env vars piped as CLI args can be empty strings. Replace `len(sys.argv) > 1` with `len(sys.argv) > 1 and sys.argv[1]`. Non-blocking hooks should exit 0 silently when context is missing.
- **[2026-05-09] Module renames break hook configs silently**: Renaming `synapse/` to `src/` left stale references in `~/.claude/settings.json` (hooks, MCP), causing silent failures. After refactoring, grep for old module name in config files, docs, and entry points.
- **[2026-05-10] Docker build needs all pyproject.toml referenced files**: hatchling requires README.md, LICENSE etc. at build time. Missing files cause cryptic `metadata-generation-failed` errors. Copy all `[project]` table referenced files before `pip install .` in Dockerfile.
- **[2026-05-17] Daemon reliability checklist**: Every background service needs: (1) PID file on startup + removal on shutdown, (2) try/except wrappers on all external dependencies with degraded-mode fallback, (3) Docker restart policy, (4) `/health` endpoint for all critical deps, (5) audit log table for scheduled jobs.

## Pipeline & Integration

- **[2026-05-14] Auto-extract metadata at ingestion boundaries**: The `concepts` parameter was always `None` because no caller extracted hashtags. Add `extract_concepts(content)` as default at the boundary function — zero caller changes, all future pushes get extraction automatically.
- **[2026-05-14] Frontend async callbacks must trigger state updates**: Chat `onSources` callback updated a local variable but didn't call `setMessages`, so citation badges never rendered. Every async data arrival point needs its own state pathway in React streaming.
- **[2026-05-14] Patch the source module, not the consumer**: `startup()` does `from src.registry import restore_registry_backup` locally. Patching `src.main.restore_registry_backup` fails — the name isn't bound in `src.main`. Always check the import statement's module path before writing `unittest.mock.patch` targets.
- **[2026-05-27] pgvector replaces Qdrant — key patterns**: (1) Use EXISTS subquery for tag-filtered vector search to avoid DISTINCT + pgvector ordering conflicts. (2) Manually format Python lists to `'[x,y,z]'::vector` — asyncpg doesn't auto-serialize. (3) Batch tag enrichment via `ANY($1)` instead of per-doc queries. (4) IVFFlat index notice after TRUNCATE is harmless.
- **[2026-05-28] Dual-storage tags need N-path enrichment**: When tags live in both JSONB column AND junction table, every read path must enrich from the junction table. 3 gaps found: `search_similar()` had zero enrichment, RRF merge used first-write-wins (dense beat FTS), and `list_docs()` didn't SELECT tags. Fix: add enrichment + use set union merge + integration tests per path.
