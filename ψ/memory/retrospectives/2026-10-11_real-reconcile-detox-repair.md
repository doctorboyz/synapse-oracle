# Retro: Real reconcile run #1 + detox resolution defects (11/10/26)

**Task**: คุณหมอสั่งผ่าน Hermes — push v3 + dry-run บน production แล้ว "รัน reconcile จริงเลย supersede ตาม draft นั้น"
**Duration**: ต่อจาก session audit (พ.ค. session เดียวกัน) · **Branch**: v3 · **Tests**: 675 passed (เพิ่ม 1 causal test)

## เกิดอะไรขึ้น

1. Push v3 → dry-run สะอาด (defrag 0 dups; detox 1 conflict would_resolve)
2. รัน reconcile จริง → รายงาน "2 conflicts resolved" — **แต่ verify หลังรันพบ state เสีย 2 จุด**:
   - merged docs (784017f9, 541ec887) embedding = NULL → dense หาไม่เจอ (audit-item-1 pattern instance ที่ 4 — แก้ไปแล้วใน MCP/CLI แต่พลาด detox)
   - supersede กลับทิศ: judge ตอบ `supersede_id: "a"` = A ชนะ/B ล้าสมัย แต่โค้ด supersede ตัว A แล้วปล่อย B (ล้าสมัย) live + embedded ต่อ

## สิ่งที่แก้

- **detox resolve → push pipeline**: `push.supersede_and_reindex` (embed + chunk + cache invalidate ผ่าน shared Push จาก CLI)
- **ทิศทางถูกต้อง + merge แทนที่ทั้งสองฝ่าย**: loser ถูก supersede, winner ถูก retire ด้วย `pg.mark_superseded` ใหม่ (additive, ไม่แตะ schema) — ไม่งั้นคู่ (winner, merged) จะเป็น near-dup ที่ detox รอบหน้าเจาะจงซ้ำ
- **Churn guard**: doc ที่ retire รอบเดียวกันห้ามถูกจับคู่วิเคราะห์อีก (กัน merged doc โดน re-merge กับของที่เหลือ)
- **Repair production** (backup `synapse_pre_detox_repair_20261011.dump` ก่อน): embed+chunk merged docs, retire outdated 2 ตัว, เคลียร์ stale embedding ของ winner ที่ retire ไปแล้ว, embed doc เก่า unembedded อีก 2 ตัว → **97 live / 97 embedded / 0 retired-still-embedded**, dry-run รอบสองสะอาด (0 dups, 0 conflicts, 0 llm_errors)

## บทเอกจากงานนี้

1. **Reconcile self-report ≠ ผลลัพธ์จริง** — คำสั่ง "รันจริง" ต้องเช็ค vault หลังรันเสมอ (embedded? superseded? live?) ถ้าเราเชื่อ JSON ที่มันพิมพ์ งานจบด้วย vault ที่หาความรู้ใหม่ไม่เจอ + ความรู้ล้าสมัยยังโผล่ในผลค้นหา
2. **Bug pattern เดียวหลบซ่อนได้ในหลาย call site** — "raw pg.supersede ไม่ embed" เกิดซ้ำ 4 จุด เพราะ pg.supersede เป็น low-level primitive ที่คนลืมว่าต้องต่อ embed เอง → บทเรียน: ต่อไปควรทำ pg.supersede embed เองหรือห้ามเรียกนอก push pipeline
3. **Merge semantics ต้องชัดว่า "แทนที่ทั้งคู่"** — ปล่อย winner live คือสร้าง duplicate ให้รอบถัดไป

## ค้าง

- 2 outdated docs (1660218d, ac04a226) ถูก retire แล้วแต่ยังอยู่ใน vault ตามหลัก nothing-is-deleted — ตรวจได้ผ่าน supersede_log
- `pg.supersede` ยังเป็น primitive ที่ไม่ embed — ถ้ามีคนเรียกจากที่ใหม่อีกจะเกิด bug เดิม (ควร wrap หรือ deprecate)