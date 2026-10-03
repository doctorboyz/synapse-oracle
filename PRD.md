# Synapse v4 — Product Requirements Document

> "PostgreSQL Single Source of Truth" — pgvector replaces Qdrant, one database for everything

## Vision

**Synapse คือ backend ให้ Obsidian** — ไม่ใช่ file manager, ไม่ใช่ note editor

```
Synapse สร้าง/อัปเดตความรู้ → เขียน .md พร้อม [[wikilinks]] ลง Obsidian vault
                                    ↓
          Obsidian (frontend/editor) — user เห็น linked notes, แก้ไขได้อิสระ
                                    ↓
Synapse scan ไฟล์ที่เปลี่ยน → re-index vector database (supersede, never delete)
                                    ↓
          User ถาม → Synapse ค้น vector DB → ตอบด้วย context + citations
```

### บทบาท

| Component | Role |
|-----------|------|
| **Synapse** | Brain — PostgreSQL+pgvector, LLM, embedding, search, reconcile, LINE chatbot |
| **Obsidian** | Interface — file manager, editor, graph view, backlinks |
| **User** | Creator — เขียน, แก้ไข, ถามคำถาม ผ่าน Obsidian หรือ MCP |

### หลักการสำคัญ

1. **Obsidian จัดการไฟล์** — Synapse อ่านจาก/เขียนลง Obsidian vault, ไม่สร้าง file system ของตัวเอง
2. **Synapse เป็นสมอง** — จัดการ database, vectors, LLM processing, search, reconciliation
3. **Bidirectional** — Synapse เขียนความรู้ไป Obsidian; Obsidian edits feed back to Synapse
4. **[[wikilinks]] format** — Synapse output ใช้ Obsidian link format ให้ connected notes
5. **Nothing is Deleted** — ไฟล์ที่อัปเดตใช้ supersede, ไม่เคยลบ
6. **YAML frontmatter** — Metadata ใน .md files ให้ Obsidian ค้นหาและกรองได้

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Obsidian Vault                       │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌──────────┐  │
│  │ note1.md│  │ note2.md│  │ note3.md│  │  .obsidian│  │
│  │[[note2]]│  │[[note1]]│  │[[note1]]│  │  (config) │  │
│  └─────────┘  └─────────┘  └─────────┘  └──────────┘  │
└──────────┬──────────────┬───────────────────────────────┘
           │   write .md  │  scan files
           ▼              ▼
┌─────────────────────────────────────────────────────────┐
│                      Synapse v4                           │
│  ┌──────────────────────┐  ┌──────────┐  ┌─────────┐   │
│  │ PostgreSQL+pgvector  │  │  Ollama  │  │ OpenRouter│  │
│  │ (FTS + vectors)      │  │ (embed)  │  │ (LLM)   │   │
│  │ Single source of truth│ └──────────┘  └─────────┘   │
│  └──────────────────────┘                                │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │  API / MCP / CLI / LINE Bot                       │   │
│  │  • synapse_search  • synapse_push                 │   │
│  │  • synapse_write_to_obsidian  • synapse_init      │   │
│  │  • LINE /ask, /search, auto-ingest                │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

## Data Flow

### Flow 1: New Knowledge → Obsidian
```
User/Agent → synapse_push → PG + Qdrant → write_to_obsidian → .md in vault
```

### Flow 2: Obsidian Edit → Synapse
```
User edits .md in Obsidian → scan detects content_hash change → supersede + re-index
```

### Flow 3: Query
```
User asks question → hybrid search (FTS + vector) → LLM synthesis → answer with citations
```

## Features

### Obsidian Writer
- เขียนเอกสารเดี่ยวหรือ batch จาก search results
- YAML frontmatter: tags, concepts, source, synapse_doc_id, created_at
- [[wikilinks]] จาก trace chain (related documents)
- Filename sanitization + collision avoidance

### Updated File Detection
- เปรียบเทียบ `content_hash` ระหว่างไฟล์กับ database
- Hash ตรงกัน → skip (no change)
- Hash ต่างกัน → supersede + re-index ใน PG และ Qdrant

### Post-Scan Auto-Write
- Scheduler ตรวจพบ Obsidian vault (`.obsidian/` directory)
- หลัง scan ถ้ามีไฟล์ถูก supersede → auto-write กลับไปที่ vault

### MCP Integration
- `synapse_write_to_obsidian` tool สำหรับ Claude Code
- รองรับ single doc (`doc_id`) และ search results (`query`)

## Configuration

```bash
# .env หรือ environment
OBSIDIAN_VAULT_PATH=/Users/doctorboyz/Obsidian/main
```

## API

### `POST /api/write-to-obsidian`
```json
{
  "doc_id": "uuid",
  "query": "search term",
  "tags": ["tag1"],
  "limit": 5,
  "vault_path": "/override/path",
  "subdir": "synapse-imports"
}
```

## MCP Tool

### `synapse_write_to_obsidian`
- `doc_id` — single document UUID
- `query` + `tags` + `limit` — write top N search results
- `vault_path` — override OBSIDIAN_VAULT_PATH
- `subdir` — optional subdirectory

---

> "ความรู้ไม่ใช่สิ่งที่เราเก็บ แต่มันคือสิ่งที่เราเชื่อมโยง" — Synapse Oracle
