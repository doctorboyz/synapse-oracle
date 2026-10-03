# ψ Vault Consolidation Report — 2026-05-28

> Cross-repo vault consolidation to reduce token usage per session.

## Summary

| Repo | Before | After | Reduction | Method |
|------|--------|-------|-----------|--------|
| synapse | 50 files | 21 files | -58% files, -40% size | Learnings 14→1, retros 11→1, /learn old snapshot deleted |
| emily-oracle | 86 files | 47 files | -45% files | Learnings 21→7, retros 28→2, archive kept |
| dev-oracle | 142 files | 132 files | -7% files | Learnings 5→1, retros 7→1, blueprints/knowledge kept |
| infra-oracle | 35 files | 23 files | -34% files | Learnings 6→1, retros 8→1 |
| myfam | 31 files | 3 files | -90% files, -94% size | Learnings 14→1, retros 14→1, /learn old snapshot deleted |
| emily-skill-cli | 10 files | 8 files | -20% files | Learnings 2→1, retros 2→1 |
| **god-port-oracle** | 120 files | — | **PENDING** | Rate limited (429) |
| **nexus-oracle** | 1650 files | — | **PENDING** | Rate limited (429) |

## Consolidated Repos (6 of 8 done)

### synapse (this repo)
- Learnings: 14 individual → `2026-05_summary.md` (3 categories)
- Retros: 11 + 9 date dirs → `2026-05_summary.md` (grouped by week)
- /learn: Deleted 2026-05-05 snapshot (superseded by 2026-05-14)

### emily-oracle
- Learnings: 17 dated → 2 monthly summaries (Apr + May), 4 topic files kept
- Retros: 28 files across 21 date dirs → 2 monthly summaries
- Archive: 26 kappa-original files kept (historical, Principle 1)

### dev-oracle
- Learnings: 5 dated → `2026-05_summary.md`, 14 topic subdirs kept
- Retros: 7 files across 5 date dirs → `2026-05_summary.md`
- Blueprints (49 files), gates (5), knowledge, projects: kept as-is

### infra-oracle
- Learnings: 6 dated → `2026-05_summary.md` (11 consolidated lessons)
- Retros: 8 files across 7 date dirs → `2026-05_summary.md` (4 weeks)

### myfam
- Learnings: 14 files (39KB) → 1 summary (5.5KB), **85.8% size reduction**
- Retros: 14 files (132KB) → 1 summary (9KB), **93.2% size reduction**
- /learn: Deleted 2026-05-08 snapshot (superseded by 2026-05-14)

### emily-skill-cli
- Learnings: 2 files → `2026-04_summary.md`
- Retros: 2 files → `2026-04_summary.md`

## Skipped Repos (too small to consolidate)

| Repo | Files | Reason |
|------|-------|--------|
| hzc-oracle | 9 | Only /learn output + roadmap, no learnings/retros |
| csuite | 17 | Domain-knowledge (sales data), 1 learning file |
| Lita-Game | 9 | 1 learning + 1 retro, too few to consolidate |
| omni-chat | 0 | Empty vault |

## Pending Repos (2)

### god-port-oracle (120 files)
- 28 learnings (Apr-May) → need monthly summaries
- ~20 retros (Apr-May) → need monthly summaries
- Sub-oracles (broky, metty) each have 2-3 files
- /learn with 2 snapshots

### nexus-oracle (1,650 files)
- 16 learnings → need monthly summary
- 4 retros → need monthly summary
- 824 inbox files → need monthly compression
- 575 dispatch files → need monthly compression
- 213 outbox files → need monthly compression

## Token Impact Estimate

| Area | Before (token load per skill read) | After | Savings |
|------|-------------------------------------|-------|---------|
| Learnings scan | ~25 individual files × 150 tokens | 1-2 summaries × 300 tokens | ~90% |
| Retros scan | ~15 individual files × 200 tokens | 1-2 summaries × 500 tokens | ~85% |
| /learn old snapshots | 3-6 files × 500 tokens | 0 (deleted) | 100% |

**Overall**: Skills that read ψ/memory/ now load ~5-10% of the previous token count for learnings and retrospectives.

## Method Used

For each repo:
1. Read all individual learning/retrospective files
2. Consolidate into monthly summaries (3-5 lines per lesson/session)
3. Verify summary is complete
4. Delete individual files and empty directories
5. Update MEMORY.md as vault index
6. Report before/after stats