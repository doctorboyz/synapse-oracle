# Synapse v4 — Roadmap

> Set: 2026-05-27 23:19 | Previous: [ψ/memory/roadmap/2026-05-27.md](roadmap/2026-05-27.md)

## Identity
- **Oracle**: Synapse v4
- **Human**: doctorboyz
- **Born**: 2026-04-21
- **Theme**: 🧠 PostgreSQL Single Source of Truth — pgvector replaces Qdrant, one database for everything

## Vision

**Synapse คือ backend ให้ Obsidian และ LINE** — PostgreSQL-only architecture with pgvector for hybrid search (FTS + vector in one SQL call). No more dual-store complexity. LINE chatbot for Q&A and knowledge ingestion. Obsidian bidirectional sync.

---

## Architecture (v4)

```
Source → push_text(chunk+embed) → PostgreSQL(pgvector) → hybrid_search(one SQL call)
```

- PostgreSQL with pgvector extension (vector(768))
- IVFFlat index for cosine similarity
- Hybrid search: FTS tsvector + pgvector cosine distance, merged via RRF
- Tag-based filtering via EXISTS subquery (avoids DISTINCT conflicts)
- document_chunks for long documents (>1500 chars, 200 overlap)
- tag_rules, scheduled_tasks, alert_log for tag-based assistant infra

---

## Active Goals

### G-001: v4 Migration — PostgreSQL Single Source of Truth
- **Status**: completed
- **Priority**: critical
- **Phase**: short-term
- **Definition of Done**: Qdrant removed, pgvector fully operational, all tests pass, Docker deployed
- **Created**: 2026-05-27
- **Updated**: 2026-05-27

#### Objectives
| ID | Objective | Status | Evidence | Updated |
|----|-----------|--------|----------|---------|
| O-1 | Schema + pgvector extension | completed | `src/db/schema.sql` — vector(768), IVFFlat, hybrid_search() | 2026-05-27 |
| O-2 | PgStore pgvector methods | completed | `src/db/pg_store.py` — set_embedding, search_similar, mark_superseded | 2026-05-27 |
| O-3 | Push pipeline pgvector | completed | `src/ingest/push.py` — stores embeddings in PG | 2026-05-27 |
| O-4 | HybridSearch pgvector | completed | `src/retrieve/hybrid_search.py` — single DB hybrid search | 2026-05-27 |
| O-5 | Reconcile pgvector | completed | `src/reconcile/defrag.py`, `detox.py` | 2026-05-27 |
| O-6 | Delete QdrantStore + config | completed | `src/db/qdrant_store.py` deleted | 2026-05-27 |
| O-7 | Delete hook_handler | completed | `src/ingest/hook_handler.py` deleted | 2026-05-27 |
| O-8 | Docker deploy + health check | completed | pg: true, embedding: true, no Qdrant | 2026-05-27 |
| O-9 | LINE source formatting + tags | completed | `_format_source_line()`, `_format_source_context()` | 2026-05-27 |
| O-10 | Database clean slate | completed | All 16 tables truncated | 2026-05-27 |

#### Audit Trail
- 2026-05-27 23:19 — v4 migration complete (10/10 objectives)

#### Blockers
_(none)_

---

### G-002: LINE Chatbot — Knowledge Q&A + Ingestion
- **Status**: completed
- **Priority**: critical
- **Phase**: short-term
- **Definition of Done**: LINE bot handles /ask, /search, auto-ingest, group/room/DM, tags displayed
- **Created**: 2026-05-27
- **Updated**: 2026-05-27

#### Objectives
| ID | Objective | Status | Evidence | Updated |
|----|-----------|--------|----------|---------|
| O-1 | LINE webhook handler | completed | `src/api/line_handler.py` | 2026-05-27 |
| O-2 | /ask command (LLM Q&A with sources) | completed | OpenRouter + pg.search_fts | 2026-05-27 |
| O-3 | /search command (FTS results) | completed | pg.search_fts with tag-enriched results | 2026-05-27 |
| O-4 | Auto-ingest (text, image OCR, location) | completed | Push pipeline with dedup | 2026-05-27 |
| O-5 | Group/room silent mode | completed | No auto-reply in groups | 2026-05-27 |
| O-6 | Task detection + supersede | completed | `_extract_task_info()`, `_find_existing_task()` | 2026-05-27 |
| O-7 | Source display with tags | completed | Helper functions include #tags | 2026-05-27 |

#### Audit Trail
- 2026-05-27 23:19 — LINE chatbot complete (7/7 objectives)

#### Blockers
_(none)_

---

### G-003: Chunking + Tag Assistant Infrastructure
- **Status**: in-progress
- **Priority**: high
- **Phase**: short-term
- **Definition of Done**: Long documents chunked, tag-based assistant rules active
- **Created**: 2026-05-27
- **Updated**: 2026-10-11

#### Objectives
| ID | Objective | Status | Evidence | Updated |
|----|-----------|--------|----------|---------|
| O-1 | chunk_text() (1500 chars, 200 overlap) | completed | `src/ingest/push.py` CHUNK_SIZE=1500, CHUNK_OVERLAP=200 — `_chunk_and_embed()` in push pipeline | 2026-10-11 |
| O-2 | document_chunks with embeddings | completed | `Push._chunk_and_embed()` writes + embeds chunks on push/supersede; causal test `test_supersede_long_doc_chunks_reindexed` | 2026-10-11 |
| O-3 | search_chunks() method | completed | `src/db/pg_store.py:1384` — wired into dense path via `_dense_with_chunks` (audit item 2, 11/10/26); keyword past 4000-char truncation found dense (R@5 12/12) + `matched_chunk_content` rides along | 2026-10-11 |
| O-4 | tag_rules auto-classification | pending | — | 2026-05-27 |
| O-5 | scheduled_tasks with alerting | pending | — | 2026-05-27 |
| O-6 | alert_log → LINE notifications | pending | — | 2026-05-27 |

#### Audit Trail
- 2026-10-11 15:04 — O-1/O-2/O-3 completed — chunking was already built but unwired (audit item 2: "search_chunks เขียนแล้วไม่มีใครเรียก"); knowledge-network audit wired it into the dense path with chunk-level RRF. Status pending → in-progress (tag assistant 3 objectives remain)
- 2026-05-27 23:19 — pending (schema ready, implementation needed)

#### Blockers
- [DEPENDENCY] Tag assistant needs LINE notification pipeline

---

### G-004: Test Suite Update
- **Status**: completed
- **Priority**: high
- **Phase**: short-term
- **Definition of Done**: All tests pass, no Qdrant references, 80%+ coverage
- **Created**: 2026-05-27
- **Updated**: 2026-05-28

#### Objectives
| ID | Objective | Status | Evidence | Updated |
|----|-----------|--------|----------|---------|
| O-1 | Fix test_config.py | completed | Port values fixed | 2026-05-27 |
| O-2 | Fix test_api_routes.py | completed | Qdrant references removed | 2026-05-27 |
| O-3 | Fix test_line_handler.py | completed | QdrantStore monkeypatches removed | 2026-05-27 |
| O-4 | Fix test_line_handler_v2.py | completed | QdrantStore monkeypatches removed | 2026-05-27 |
| O-5 | Fix test_scheduler.py | completed | Qdrant references removed | 2026-05-27 |
| O-6 | Fix test_local_only.py | completed | qdrant_url references removed | 2026-05-27 |
| O-7 | Fix test_push.py | completed | QdrantStore references removed | 2026-05-28 |
| O-8 | Fix remaining test files | completed | hybrid_search, lifecycle, mcp_server, hooks_installer, pg_store — all pass | 2026-05-28 |
| O-9 | Delete test_qdrant_store.py | completed | File deleted | 2026-05-27 |
| O-10 | Delete test_hook_handler.py | completed | File deleted | 2026-05-27 |
| O-11 | Full test suite passes (80%+) | completed | 567 passed, 4 warnings | 2026-05-28 |

#### Audit Trail
- 2026-05-28 13:06 — G-004 complete (11/11) — 567 tests pass, 0 failures
- 2026-05-27 23:19 — 8/11 objectives complete

#### Blockers
_(none)_

---

### G-005: Claude Ingest Pipeline (Replacement)
- **Status**: pending
- **Priority**: medium
- **Phase**: mid-term
- **Definition of Done**: New mechanism to auto-ingest Claude session knowledge into synapse
- **Created**: 2026-05-27
- **Updated**: 2026-05-27

#### Objectives
| ID | Objective | Status | Evidence | Updated |
|----|-----------|--------|----------|---------|
| O-1 | Design new ingest mechanism | pending | hook_handler deleted | 2026-05-27 |
| O-2 | Implement + test | pending | — | 2026-05-27 |
| O-3 | Deploy to all Oracle repos | pending | — | 2026-05-27 |

#### Audit Trail
- 2026-05-27 23:19 — pending (user said "ยังไม่ต้องทำ")

#### Blockers
- [DEPENDENCY] User wants to pause this for now

---

### G-006: Frontend — Visual Overview, Upload, Clipping
- **Status**: in-progress
- **Priority**: high
- **Phase**: mid-term
- **Definition of Done**: Browse, upload, clip, and visualize knowledge
- **Created**: 2026-05-16
- **Updated**: 2026-05-27

#### Objectives
| ID | Objective | Status | Evidence | Updated |
|----|-----------|--------|----------|---------|
| O-1 | Document list with filters | completed | `frontend/src/shared/hooks/useDocuments.ts` | 2026-05-16 |
| O-2 | Knowledge graph visualization | completed | `frontend/src/features/knowledge-graph/` | 2026-05-16 |
| O-3 | Search interface | completed | `frontend/src/features/search/` | 2026-05-16 |
| O-4 | Chat Q&A with citations | completed | `frontend/src/features/chat/` | 2026-05-16 |
| O-5 | Upload files | completed | `frontend/src/features/upload/` | 2026-05-16 |
| O-6 | Push documents manually | completed | `frontend/src/features/push/` | 2026-05-16 |
| O-7 | Web clipping (browser extension) | pending | — | 2026-05-16 |
| O-8 | Mobile app / PWA | pending | — | 2026-05-16 |
| O-9 | Dashboard overview (stats, trends) | pending | — | 2026-05-16 |

---

### G-007: Obsidian Bidirectional Integration
- **Status**: completed
- **Priority**: critical
- **Phase**: short-term
- **Definition of Done**: Synapse reads/writes Obsidian vault bidirectionally
- **Created**: 2026-05-26
- **Updated**: 2026-05-27

#### Objectives
| ID | Objective | Status | Evidence | Updated |
|----|-----------|--------|----------|---------|
| O-1 | Obsidian Writer (.md + YAML + [[wikilinks]]) | completed | `src/ingest/obsidian_writer.py` | 2026-05-26 |
| O-2 | Updated file detection + supersede | completed | `src/ingest/init_scan.py` | 2026-05-26 |
| O-3 | POST /api/write-to-obsidian | completed | `src/api/routes.py` | 2026-05-26 |
| O-4 | synapse_write_to_obsidian MCP tool | completed | `src/mcp/server.py` | 2026-05-26 |
| O-5 | Scheduler post-scan auto-write | completed | `src/scheduler.py` | 2026-05-26 |

---

### G-008: Knowledge Network Quality — เก็บได้ เรียกได้ เรียนได้ เชื่อมโยงได้
- **Status**: completed
- **Priority**: critical
- **Phase**: short-term
- **Definition of Done**: Ada audit 8 ข้อแก้ครบ + reconcile production รันจริงสะอาด + R@5 100% + bug pattern ปิดถาวร
- **Created**: 2026-10-11
- **Updated**: 2026-10-11

#### Objectives
| ID | Objective | Status | Evidence | Updated |
|----|-----------|--------|----------|---------|
| O-1 | Audit 8 ข้อแก้ครบ (embed/chunk/filter/cache/N+1/error/benchmark) | completed | commit `2466f69`, causal tests ×16, 674→678 tests pass | 2026-10-11 |
| O-2 | R@5 100% hybrid+dense (จาก 83%/75%) | completed | `benchmarks/results/r_at_5_{before,after,run2_post_reconcile}.json` — 100% คง 3 runs | 2026-10-11 |
| O-3 | Reconcile รันจริงบน production สะอาด | completed | รอบ1 2 conflicts (พบ defect) → fix+repair → รอบ2 0 conflicts; vault 97 live/97 embedded/0 stale | 2026-10-11 |
| O-4 | Detox resolve defect แก้ (unembed + ทิศกลับ) | completed | ISSUE-011, commit `8265976`, causal test `TestDetoxResolution` | 2026-10-11 |
| O-5 | Raw pg.supersede deprecated + call sites ชง pipeline หมด | completed | commit `ff02749`, source-guard test กัน pattern กลับมา | 2026-10-11 |
| O-6 | Test suite ไม่เขียน production (ISSUE-010) | completed | conftest บังคับ SYNAPSE_DB_URL=test DB, pollution เก็บกวาด 107→100 docs | 2026-10-11 |
| O-7 | Merge v3 → main | completed | fast-forward `138195f`→`b134b6e`, 678 tests ผ่านบน main ก่อน push | 2026-10-11 |

#### Audit Trail
- 2026-10-11 15:04 — goal complete (7/7 objectives) — งานจากคำสั่งคุณหมอผ่าน Hermes, audit โดย Ada

#### Blockers
_(none)_

---

## Completed Goals
- **G-001**: v4 Migration — PostgreSQL Single Source of Truth (2026-05-27)
- **G-002**: LINE Chatbot — Knowledge Q&A + Ingestion (2026-05-27)
- **G-004**: Test Suite Update (2026-05-28)
- **G-007**: Obsidian Bidirectional Integration (2026-05-26)
- **G-008**: Knowledge Network Quality (2026-10-11)

## Archived Roadmaps
- [2026-05-27 roadmap](roadmap/2026-05-27.md) — Previous v3 roadmap (PostgreSQL+Qdrant)
- [2026-05-16 roadmap](roadmap/2026-05-16.md) — Original v3 roadmap (4 goals)
