---
respond_to: hermes
task: ISSUE-009 follow-up / knowledge-network audit (Ada 11/10/26)
status: done
date: 2026-10-11
---

# Synapse Knowledge Network — เสร็จครบ 8/8 audit items

สรุปงานตามคำสั่งคุณหมอ (จาก PM group, audit โดย Ada 11/10/26): แก้ synapse ให้เป็น "โครงข่ายความรู้" จริง — เก็บได้ เรียกได้ เรียนได้ เชื่อมโยงได้

## ตัวเลขยืนยันจากการรันจริง (benchmark R@5, corpus 13 docs, 12 ground-truth queries, real Ollama)

| Metric | ก่อนแก้ | หลังแก้ |
|---|---|---|
| **hybrid R@5** | 83% (10/12) | **100% (12/12)** |
| **dense R@5** | 75% (9/12) | **100% (12/12)** |
| first-query latency | 42.3ms | 29.2ms |
| cache repeat query | — | 0.0ms (cache ทำงานจริง) |
| supersede→dense findable | ✅ | ✅ (live verify ผ่าน MCP stdio 8/8) |

## แก้ตาม audit ทั้ง 8 ข้อ

1. **Supersede ไม่ embed ใหม่** — MCP (`src/mcp/server.py`) และ CLI (`src/main.py`) ใช้ raw `pg.supersede` + `clear_embedding` ทิ้ง embedding ใหม่หายเงียบ → ตอนนี้ทั้งคู่ผ่าน `push.supersede_and_reindex` (รองรับ `new_title` ด้วย)
2. **`search_chunks` เขียนแล้วไม่มีใครเรียก** — dense path ตอนนี้ merge doc-level + chunk-level ANN (`_dense_with_chunks`) doc ยาว >4000 chars หา keyword หลังจุด truncate ได้แล้ว + `matched_chunk_content` ติดมากับผลลัพธ์
3. **concepts filter รับแล้วเฉย + ghost tool + SQL injection** — filter ทำงานจริงทั้ง fts/dense/hybrid, `synapse_fix_doctype` ลง TOOL_DEFINITIONS แล้ว (เรียกได้จริง), relation ใน trace parameterize หมด (ปิด injection `relation = "x' OR ..."`)
4. **embed_batch จอมปลอม** — ส่ง ONE `/api/embed` call พร้อม input array จริง + persistent httpx client (เดิม serial loop + สร้าง client ใหม่ทุก call)
5. **SearchCache สร้างแล้วไม่ต่อ** — ต่อครบ CLI/MCP/API, cache key ครบทุก filter (doc_type/oracle/source_project/concepts — เดิมชนกันได้), push/supersede invalidate, ทุก mode (dense/fts/hybrid) ใส่ cache ได้ (เดิมเฉพาะ hybrid)
6. **defrag N+1** — phase 1 ใช้ `list_doc_hashes` คำสั่งเดียว (เดิม list 10k + get ทีละ doc)
7. **MCP error bare str(e)** — `_format_tool_error` บอก tool+param; **พบเพิ่มว่า SDK validation error ก็ไม่บอก tool** → ย้าย validation เข้า handler (`validate_input=False`)
8. **benchmark ตาย (import sqlite_store)** — `benchmarks/r_at_5.py` ใหม่: R@5 + latency + supersede-flow check, รันบน DB ทิ้ง (synapse_bench) ไม่แตะ production

## สำคัญ: พบ ISSUE-010 (critical) ระหว่างทำ — production vault เคยโดน test เขียน

- **อาการ**: init_scan tests สร้าง `Settings()` ของตัวเอง และ `SYNAPSE_DB_URL` (ชี้ production) ชนะ `DATABASE_URL` ตาม design → test suite เขียนลง vault จริง **7 test docs** (6 จาก 8/10 + 1 จาก suite run วันนี้)
- **เก็บกวาดแล้ว**: backup `~/.hermes/cache/backups/synapse_pre_issue010_cleanup_20261011.dump` ก่อนลบ → ลบ 7 docs + supersede_log/document_tags + test tags ใน transaction เดียว → vault ตอนนี้ **100 docs / 97 embedded / 99 live** (init_scan rows = 0) ข้อมูลจริง สปส./clinic ไม่โดนเด็ดขาด ตรวจสอบแล้ว
- **กันซ้ำถาวร**: `tests/conftest.py` บังคับ `SYNAPSE_DB_URL=synapse_test` ทั้ง test session — ไม่ว่า shell จะ export อะไรมา ทุก `Settings()` ใน test จะตกที่ test DB เสมอ
- **บั๊กเพิ่มที่พบและแก้แล้วในงานเดียวกัน**: hybrid ตัด candidate pool ก่อน RRF (limit*2) จน doc ที่อีกฝั่ง rank 1 หายเงียบ → pool = max(limit*4, 20); test_config อ้าง env priority กลับด้านจาก design จริง (stale test)

## การ verify (ตาม mandatory framework)

- **Causal tests**: `tests/test_knowledge_network.py` 16 tests — RED→GREEN ครบ ทุก fix มี test ยืนยันพฤติกรรมจริง
- **Full suite**: 674 passed, 0 failed (เดิม 11 failed — 6 defrag mock, 4 init_scan (จริงๆ คืออาการ ISSUE-010), 1 config stale)
- **Live MCP stdio** (test DB + Ollama จริง): 8/8 ✅ — supersede→dense เจอ doc ใหม่, long-tail keyword เจอทาง hybrid + chunk content ติดมา, error บอก tool+param, fix_doctype เรียกได้, reconcile_log มี staleness
- **R@5 before/after**: ดูตารางบน — รายงาน JSON อยู่ที่ `benchmarks/results/r_at_5_{before,after}.json`
- **Production safety**: pg_dump backup ก่อนแตะ DB ทุกครั้ง (2 ชุด: pre-work + pre-cleanup), pollution เก็บกวาด verify แล้ว

## ค้างไว้ให้ session ถัดไป

1. รัน `synapse reconcile` จริงบน production ครั้งแรก (แนะนำ `--dry-run` ก่อน) เพื่อ refresh staleness — ตอนนี้ reconcile_log ยัง never_run
2. `search_chunks` ยังไม่รับ concepts/tags filter ตอน query (merge ตอนหลังแทน) — พอใช้ได้กับ corpus ปัจจุบัน ถ้า vault โตควร filter ที่ chunk query ตรงๆ
3. benchmark R@5 ควรเข้า CI แบบ optional (ต้องใช้ Ollama)
4. ควรมี e2e guard ที่ fail ถ้า `pytest` ได้ `database_url` = production pattern (defense-in-depth เหนือ conftest pin)

Commit: `fix: knowledge-network audit — stored knowledge must be findable (8 items)` บน branch `v3` · Retro: `ψ/memory/retrospectives/2026-10-11_knowledge-network-audit.md` · Issue log: ISSUE-010 ใน `ψ/issues/issues.jsonl`