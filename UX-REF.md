# Synapse v4 — UX Reference

> LINE Chatbot + React Frontend user experience

## LINE Chatbot UX

### Commands

| Command | UX | Example |
|---------|-----|---------|
| `/ask <question>` | LLM answers with sources + tags | `/ask เล่าเรื่องเส้นทางสายไหม` → answer + 📚 sources |
| `/search <query>` | FTS results with metadata | `/search pgvector` → 🔍 results with #tags |
| `/tags` | List all tags with counts | `/tags` → 🏷️ Tags: line (5), learning (3) |
| `/recent [scope]` | Latest 5 documents | `/recent` → 📄 เอกสารล่าสุด |
| `/stats` | Document + tag counts | `/stats` → 📊 สถิติ Synapse |
| `/help` | Available commands | `/help` → 🤖 command list |

### Source Display Format

```
📚 ที่มา:
  1. Silk Road Caravan Routes [learning · god-port] (demo) #history #trade
  2. Campaign Analysis [note · mkt] (mkt) #marketing
```

Format: `index. title [doc_type · oracle · source_project] (scope) #tag1 #tag2`

### Auto-Ingest UX

| Action | Reply (DM) | Reply (Group) |
|--------|-----------|---------------|
| Text message (>10 chars) | ✅ บันทึกความรู้แล้ว | _(silent)_ |
| Duplicate | 📝 ข้อมูลคล้ายกันอยู่แล้ว — ข้าม | _(silent)_ |
| Image (OCR success) | ✅ บันทึกความรู้แล้ว | _(silent)_ |
| Image (OCR fail) | _(silent — stored as note)_ | _(silent)_ |
| Sticker | _(skipped)_ | _(skipped)_ |
| Error | ❌ บันทึกไม่สำเร็จ: [error] | _(silent)_ |

### LINE Constraints

- 5000 character message limit
- Plain text only (no markdown, no HTML)
- Emoji supported (✅ ❌ 📚 🔍 🤖 📝 ❓ 📊 📄 📭 🏷️)
- Response time: aim for <3s for /search, <10s for /ask (LLM-dependent)

## React Frontend

### Pages

| Page | Route | Purpose |
|------|-------|---------|
| Chat | /chat | Q&A with knowledge base |
| Search | /search | Document search with filters |
| Knowledge Graph | /graph | Visual document relationship graph |
| Upload | /upload | File upload + ingest |
| Push | /push | Manual document creation |
| Commands | /commands | Command reference |

### Component Inventory

| Component | Location | Reusable |
|-----------|----------|----------|
| Layout | shared/components/Layout.tsx | ✅ |
| Badge | shared/components/Badge.tsx | ✅ |
| Loading | shared/components/Loading.tsx | ✅ |
| EmptyState | shared/components/EmptyState.tsx | ✅ |
| ErrorBoundary | shared/components/ErrorBoundary.tsx | ✅ |

### UX Issues (Known)

1. **No dark mode support** — LINE is always light, frontend follows OS preference
2. **Loading states inconsistent** — Chat shows spinner, Search shows nothing during query
3. **No pagination** — Document list shows fixed 20, no "load more"
4. **Empty states** — Most pages have EmptyState component but messaging is inconsistent
5. **Mobile navigation** — Bottom tabs not optimized for small screens (<375px)
