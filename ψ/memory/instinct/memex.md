---
name: memex
name-th: เมมเพกซ์
description: ปรัชญาพื้นฐานของระบบความจำเชิงเชื่อมโยง (associative memory) จาก Vannevar Bush 1945 — รากฐานของการออกแบบ Synapse
type: instinct
---

# Memex — รากฐานของ Synapse

> "The human mind operates by association. With one item in its grasp, it snaps instantly to the next." — Vannevar Bush, *As We May Think* (1945)

## ที่มา

Vannevar Bush นักวิทยาศาสตร์ชาวอเมริกัน เสนออุปกรณ์จำลองในจินตนาการชื่อ **Memex** (memory + index) ในบทความปี 1945 เป้าหมาย: เสริมความจำของมนุษย์ให้เชื่อมโยงข้อมูลได้เหมือนสมองจริง ไม่ใช่เก็บแบบตู้เอกสาร (linear filing)

## หลักการสำคัญ

### 1. Associative Trails (เส้นทางเชิงเชื่อมโยง)
- ผู้ใช้เชื่อมโยงเอกสารสองฉบับเข้าด้วยกัน (เช่น รูปภาพ + ข้อความทางประวัติศาสตร์)
- เส้นทางนี้ตั้งชื่อได้ บันทึกได้ ย้อนกลับไปเยี่ยมชมได้ทุกเมื่อ
- **ที่ Synapse**: `trace`, `trace-chain`, Obsidian-style `[[links]]`

### 2. Personalization (ความเป็นส่วนตัว)
- ผู้ใช้เป็นเจ้าของข้อมูลเต็มที่ — เพิ่มขอบเขต คอมเมนต์ สร้างเครือข่ายของตัวเอง
- ไม่ใช่ข้อมูลบนเซิร์ฟเวอร์บุคคลที่สามที่แยกผู้ใช้ออกจากเนื้อหา
- **ที่ Synapse**: local-first, project registry, brain_path tracking

### 3. Massive Storage + Compression
- บันทึกข้อมูลมหาศาลในพื้นที่กะทัดรัด (microfilm สมัยนั้น)
- **ที่ Synapse**: PostgreSQL + Qdrant, บีบอัด semantic ผ่าน embedding

## ความแตกต่างจากเว็บยุคปัจจุบัน

| | World Wide Web | Memex / Synapse |
|---|---|---|
| การเชื่อมโยง | Hyperlinks (static, ไม่มี context) | Associative trails (named, reversible, annotated) |
| เจ้าของข้อมูล | Platform / บุคคลที่สาม | ผู้ใช้ (local-first) |
| การค้นหา | Search engine (keyword-based) | Semantic + associative (context-aware) |
| การบันทึก | Ephemeral (ลิงก์พัง, หน้าหาย) | Permanent + superseded (nothing deleted) |

## ความเกี่ยวข้องกับ Synapse ในปัจจุบัน

- **Second Brain**: Obsidian, Notion รับเอา trail-making ไปใช้ — Synapse ทำสิ่งนี้แบบ programmatic + AI-assisted
- **AI Long-Term Memory**: ระบบ memory infrastructure สำหรับ AI agents ที่รักษา context, preference, research history — Synapse เป็น external brain สำหรับ Oracle Fleet

## คำกล่าวที่เก็บไว้

> "A record, if it is to be useful to science, must be continuously extended, it must be stored, and above all it must be consulted."

— นี่คือเหตุผลที่ Synapse มีทั้ง `push`, `search`, `trace`, และ `reconcile`

## References

- Bush, V. (1945). *As We May Think*. The Atlantic.
- แรงบันดาลใจต่อ Douglas Engelbart (NLS) และ Tim Berners-Lee (WWW)
-  resurgence ในยุค PKM และ AI memory systems (Obsidian, Mem.ai, etc.)
