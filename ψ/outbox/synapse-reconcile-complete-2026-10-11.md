---
respond_to: hermes
task: real reconcile run + detox repair + deprecation + merge to main (ต่อจาก knowledge-network audit)
status: done
date: 2026-10-11
---

# Synapse — reconcile จริงบน production เสร็จสมบูรณ์ + merge ขึ้น main

สรุปงานตามคำสั่งคุณหมอ 3 ต่อเนื่อง: dry-run → รันจริง supersede ตาม draft → เก็บกวาด+กันซ้ำ → merge v3 เข้า main

## 1. รัน reconcile จริง — พบ defect 2 จุดแล้วแก้ครบ (ISSUE-011)

รอบแรกรายงาน "2 conflicts resolved" **แต่ verify จาก DB จริงหลังรันพบ state เสีย** (reconcile self-report ≠ ผลลัพธ์จริง — เช็คตามบทเรียน audit):

1. merged docs embedding = NULL — detox ใช้ raw `pg.supersede` (pattern เดียวกับ audit item 1, instance ที่ 4) → ความรู้ใหม่หาไม่เจอทาง dense
2. supersede กลับทิศ — judge ตอบ `supersede_id: "a"` = A ชนะ/B ล้าสมัย แต่โค้ด retire ตัว A แล้วปล่อย B (ล้าสมัย) live ต่อ

**แก้ (CPT — causal test RED→GREEN)**: resolve path ผ่าน `push.supersede_and_reindex` (embed+chunk+invalidate cache) · ทิศทางถูกต้อง · **merge แทนที่ทั้งสองฝ่าย** ผ่าน `pg.mark_superseded` ใหม่ (additive ไม่แตะ schema) · churn guard กัน doc ที่ retire แล้วถูกจับคู่ซ้ำในรอบเดียวกัน

**ซ่อม production** (backup `synapse_pre_detox_repair_20261011.dump` ก่อนทุกจุด): embed+chunk merged docs ทั้ง 2 (verify จริง dense rank 1) · retire doc ล้าสมัย 2 ตัวเข้า merge ของตัวเอง · เคลียร์ stale embedding · embed doc unembedded เก่าอีก 2 ตัว

## 2. Reconcile รอบสอง — สะอาด ยืนยันจาก DB จริง

- defrag 0 dups · detox **0 conflicts** · 0 errors · 0 llm_errors · pairs 335
- Vault: **97 live / 97 embedded / 0 retired-still-embedded** — ทุก doc live หาได้ครบ fts/dense/hybrid
- reconcile_log 3 รายการเรียงเรื่องครบ (รอบแรก 2 conflicts → dry-run 0 → รอบสอง 0)

## 3. Deprecate raw `pg.supersede` — ปิด bug pattern ถาวร

- public `supersede` = deprecated wrapper (DeprecationWarning ชี้ `Push.supersede_and_reindex`) · raw body ย้ายเป็น `_supersede_raw`
- **เจอ call site เถื่อนเพิ่มอีก 6 จุด** ที่ audit ก่อนไม่เคยสแกน: defrag ×2, LINE task update ×2, `/api/supersede` route, — ทั้งหมดชงผ่าน push pipeline แล้ว
- **Source-guard test** สแกน src/ ทุก `.supersede(` ที่ไม่ใช่ pipeline — ใครเขียน call site เถื่อนใหม่ test แดงทันที

## 4. R@5 regression — quality ยืน 100%

| Run | hybrid R@5 | dense R@5 | cache repeat |
|---|---|---|---|
| before (ก่อน audit) | 83% | 75% | dense 33ms (ไม่ทำงาน) |
| after (จบ audit) | 100% | 100% | 0.0ms |
| post_reconcile (หลัง refactor) | **100%** | **100%** | 0.0ms |

supersede→dense findable ผ่านต่อเนื่อง 3 runs · result file `benchmarks/results/r_at_5_run2_post_reconcile.json` เป็น baseline ใหม่

## 5. Merge ขึ้น main

- v3 → main **fast-forward** (ไม่มี conflict ไม่มี force) · suite บน main ผ่าน 678 passed ก่อน push
- main ตอนนี้มีครบ: audit 8 ข้อ → ISSUE-010/011 → detox fix → deprecate+guard → benchmark baselines

## สรุป verify ทั้งหมด

- **678 tests passed, 0 failed** (เพิ่มจาก 674 — causal test detox + deprecation + source guard)
- Production vault 97 live / 97 embedded ตรวจจาก psql จริง ไม่ใช่ self-report
- Backup 4 ชุดวันนี้: pre_knowledge_network, pre_issue010_cleanup, pre_detox_repair, pre_reconcile_run2

## ค้าง (ไม่บล็อก)

- `search_chunks` ยังไม่รับ concepts/tags filter ตอน query (merge ตอนหลังแทน) — พอใช้กับ corpus ปัจจุบัน
- benchmark R@5 ควรเข้า CI แบบ optional (ต้องใช้ Ollama)
- scheduler `_run_reconcile` ยังไม่ส่ง push instance เข้า reconcile (detox สร้างเองได้ — แค่ไม่ share cache invalidation)

Retro: `ψ/memory/retrospectives/2026-10-11_real-reconcile-detox-repair.md` · Issue log: ISSUE-011 ใน `ψ/issues/issues.jsonl` · Commits: `8265976` `ff02749` `bdb79b5` (main = v3)