# Retro: Knowledge Network Audit — 8 รายการจาก Ada (11/10/26)

**Task**: ทำให้ synapse เป็น "โครงข่ายความรู้" จริง — เก็บได้ เรียกได้ เรียนได้ เชื่อมโยงได้
**Duration**: 1 session (11/10/26) · **Branch**: v3 · **Tests**: 672→674 passed, 0 failed

## ผลลัพธ์เทียบ baseline (R@5 benchmark จริง, 13 corpus docs, 12 queries)

| Metric | ก่อน | หลัง |
|---|---|---|
| dense R@5 | 75% (9/12) | **100% (12/12)** |
| hybrid R@5 | 83% (10/12) | **100% (12/12)** |
| hybrid first-query latency | 42.3ms | 29.2ms |
| repeat-query (cache hit) | 0.0ms | 0.0ms |
| supersede→dense findable | ✅ | ✅ (verify จริงผ่าน MCP stdio 8/8) |

## ที่แก้ตาม audit

1. **Supersede ไม่ embed ใหม่** (MCP + CLI ทั้งคู่) → ใช้ `push.supersede_and_reindex` + รองรับ `new_title`
2. **search_chunks เขียนแล้วไม่มีใครเรียก** → dense path รวม doc-level + chunk-level ANN (`_dense_with_chunks` + `_merge_dense_results`) พร้อม `matched_chunk_content`
3. **concepts filter รับแล้วเฉย** (fts/dense/hybrid) + ghost tool `synapse_fix_doctype` + SQL injection ที่ relation → แก้ครบ, parameterize ทุกจุด
4. **embed_batch จริงๆ คือ serial + สร้าง httpx client ทุกครั้ง** → `/api/embed` input array จริง + persistent client
5. **SearchCache สร้างแล้วไม่ต่อ** → ต่อครบทั้ง CLI/MCP/API, key ครบทุก filter, push/supersede invalidate
6. **defrag N+1** (10k get) → `list_doc_hashes` 1 query, เรียก get เฉพาะ duplicate จริง
7. **MCP error bare str(e)** → `_format_tool_error` บอก tool+param; **เพิ่มเติม**: ย้าย schema validation เข้า handler (`validate_input=False`) เพราะ error ของ SDK ไม่บอกชื่อ tool
8. **benchmark ตาย** → `benchmarks/r_at_5.py` ใหม่ R@5 + latency + supersede-flow

## บั๊กที่เจอเพิ่มระหว่างทำ (ไม่อยู่ใน audit)

- **ISSUE-010 (critical)**: test suite เคยเขียนลง production vault จริง — `SYNAPSE_DB_URL` ชนะ `DATABASE_URL` ตาม design, แต่ init_scan สร้าง `Settings()` ของตัวเองและ dev shell export SYNAPSE_DB_URL ชี้ production → 7 test docs ปนเปื้อน vault (6 จาก 8/10, 1 จาก suite run วันนี้) — **เก็บกวาดหมด** (backup ก่อนลบ, 107→100 docs, FK/supersede_log จัดการครบ) + conftest บังคับ `SYNAPSE_DB_URL=test DB` ทั้ง session ตลอดไป
- **Hybrid truncation ก่อน RRF**: pool `limit*2` ตัด doc ที่อีกฝั่ง rank สูงทิ้งก่อน fusion (kafka query พลาด) → pool `max(limit*4, 20)` เพราะ RRF k=60 ทำให้ rank-20 ยังแข่งได้
- **test_config อ้าง priority กลับด้าน**: config.py flip precedence ไปนานแล้ว แต่ test ยัง assert แบบเก่า — แก้ test ตาม design intent

## บทเรียน (lessons)

1. **สัญญา "เก็บได้" ต้องวัดจากปลายทาง**: ทุก push ต้องหาได้ทั้ง fts/dense/hybrid ระดับ doc+chunk — benchmark R@5 คือตัวเฝ้าสัญญานี้ ไม่ใช่ test ที่ mock ทุกอย่าง
2. **Test DB isolation ต้อง defuse ที่ env ไม่ใช่ที่ fixture**: conftest TEST_DB_URL ป้องกันแค่ fixture ที่ใช้ — code path ที่สร้าง Settings() เอง (init_scan, MCP server, scheduler) ต้องบังคับที่ env var สูงสุด (`SYNAPSE_DB_URL`) ใน conftest ถึงจำกัดได้ทุกทาง
3. **RRF fusion ห้าม truncate ก่อน fuse**: candidate pool ต้องกว้างเท่าที่ k-damping ยังให้คะแนนแข่งได้ — doc ที่ rank ต่างฝั่งเดียวเกิน pool จะหายเงียบแม้อีกฝั่ง rank 1
4. **Error ที่ไม่บอก tool = ไม่ใช่ error ที่ debug ได้**: ย้าย validation เข้า handler เพื่อบังคับชื่อ tool ในทุก error path รวมทั้ง schema

## สิ่งที่ค้าง (สำหรับ session ถัดไป)

- รัน `synapse reconcile` จริงบน production เพื่อ refresh staleness (ตอนนี้ reconcile_log บอก never_run บน test DB)
- `search_chunks` ยังไม่รับ concepts/tags filter (chunk hits วิ่ง across ทั้ง vault แล้ว merge ตอนหลัง) — ยอมรับได้เพราะ RRF + final filter, แต่ถ้า corpus โตควร filter ตั้งแต่ chunk query
- benchmark ควรเข้า CI แบบ optional (ใช้ Ollama จริง)
- supersede_log / trace ของ doc ที่โดน defrag compact บน production ยังไม่เคยรัน — ควร dry-run ก่อนครั้งแรก