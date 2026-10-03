# Synapse v4 — UX/UI Reference

## Tech Stack
- Frontend: React 19 + TypeScript 6 + Vite 8 + Tailwind CSS 4
- Routing: react-router-dom 7, State: Zustand 5, Icons: lucide-react
- LINE Bot: Python, plain text via LINE Messaging API

## Component Inventory

| Component | File | Lines | Reusability |
|-----------|------|-------|-------------|
| App (router) | App.tsx | 24 | Entry point |
| Layout + NavItem | Layout.tsx | 1-114 | Shell |
| KnowledgeGraphPage | KnowledgeGraphPage.tsx | 1-684 | Page (private GraphView) |
| PushPage + 4 forms | PushPage.tsx | 1-415 | Page (private subcomponents) |
| ChatPage | ChatPage.tsx | 1-629 | Page (monolithic) |
| CommandsPage | CommandsPage.tsx | 1-261 | Page |
| Badge | Badge.tsx | 1-22 | Shared, reusable |
| EmptyState | EmptyState.tsx | 1-15 | Shared |
| ErrorBoundary | ErrorBoundary.tsx | 1-67 | Shared, class-based |
| Loading | Loading.tsx | 1-10 | Shared |
| Markdown | Markdown.tsx | 1-192 | Shared, custom renderer |

ChatPage (629 lines) and KnowledgeGraphPage (684 lines) are monolithic — should extract subcomponents.

## Design System

### Colors (from index.css)
```
--color-surface: #ffffff
--color-surface-elevated: #f8fafc
--color-border: #e2e8f0
--color-text: #0f172a
--color-text-secondary: #475569
--color-text-muted: #94a3b8
--color-accent: #0ea5e9
--color-accent-hover: #0284c7
--color-success: #10b981
--color-warning: #f59e0b
--color-error: #ef4444
```

### Contrast Failures (CRITICAL)
- White on `#0ea5e9` accent: **3.4:1** (needs 4.5:1) — affects send buttons, new-chat, logo
- `#94a3b8` muted on `#f8fafc` elevated: **2.4:1** — used for 10px labels everywhere
- `#0ea5e9` accent on `#e0f2fe` subtle: **2.1:1** — Badge component

### Dead Code
- **App.css** (185 lines): Entirely unused Vite template styles — should be deleted

## Accessibility Issues

### Missing aria-labels (12+ icon-only buttons)
- Sidebar close, mobile menu, chat sidebar, delete session, send message, link popup close, copy result, clear history — all need `aria-label`

### Missing Form Labels
- Chat input, search inputs (KnowledgeGraph, CommandsPage), scope/doc-type selects — all rely on placeholder only

### Touch Targets (FAIL WCAG 2.5.5)
- Nav items: ~36px (needs 44px)
- Scope selector: ~24px
- Delete session: ~22px
- Model selector: ~24px

### Semantic HTML
- No `<main>`, `<nav>`, `<header>`, `<footer>` — uses `<div>` instead
- No skip-to-content link
- SVG graph nodes not keyboard-focusable

## Visual Hierarchy

### Heading Bug (CRITICAL)
Markdown.tsx maps `#` → `<h3>`, `##` → `<h4>`, `###` → `<h5>` — semantically wrong

### Page Headings
- Only PushPage has `<h1>` — ChatPage, CommandsPage, KnowledgeGraphPage have no heading hierarchy

### Font Sizes
- Dominant: `text-sm` (14px) — flat hierarchy
- Metadata: `text-xs` (12px) and `text-[10px]` — readability concern

## Interaction Patterns

### Loading States
- Loading.tsx: simple spinner
- ChatPage: animated send button during streaming
- PushPage: button text changes
- **Missing**: skeleton loading, no debounce on search

### Error States
- ErrorBoundary: hardcoded inline styles (bypasses design system)
- KnowledgeGraphPage: inline error card
- ChatPage: streaming errors append "Error: ..." message
- **Missing**: global toast/notification system

### Empty States
- Well-designed across all pages with actionable messaging

### Missing Patterns
- No debounce on search (fires every keystroke)
- No confirmation before delete (chat sessions)
- No Shift+Enter for multi-line chat input
- No drag-and-drop, no undo

## Mobile & Responsive

### Breakpoints
Single breakpoint: `md:` (768px) — binary mobile/desktop

### Mobile Patterns
- Sidebar: overlay with translate-x animation, auto-close on route change — well done
- KnowledgeGraph: left panel hides, detail full-screen overlay — well done

### Issues
- Graph SVG hardcoded to 900px — no mobile adaptation
- Chat sidebar w-72 too wide for mobile
- No safe area insets for notched devices

## LINE Bot UX

### Commands
/search, /ask, /recent, /stats, /scopes, /tags, /help

### Issues
- **Missing /start command** — no onboarding flow
- **No quick reply buttons or Flex Messages** — plain text only
- **Unknown command** says "ไม่รู้จักคำสั่ง" without suggesting /help
- **Error messages** leak raw Python exceptions: `f"❌ บันทึกไม่สำเร็จ: {e}"`
- **No message length enforcement** — LINE 5000-char limit not checked
- **/stats label bug**: says "Tags ทั้งหมด" but shows scope count
- **No typing indicator** during LLM calls

### Source Display (well-designed)
Format: `index. title [doc_type · oracle · source_project] (scope) #tag1 #tag2`

## Prioritized Recommendations

### CRITICAL (Fix Immediately)
1. LINE message length overflow — add truncation before _send_reply()
2. White-on-accent contrast 3.4:1 — change accent color or button text
3. No aria-labels on 12+ icon buttons
4. Dead App.css (185 lines) — delete

### HIGH (This Sprint)
1. Markdown heading mapping (# → h3 bug)
2. Search fires on every keystroke — add 300ms debounce
3. Chat streaming error leaves empty bubble
4. Unknown command doesn't suggest /help
5. No /start welcome flow
6. Error leaks internal exception text
7. ChatPage monolithic (629 lines) — extract components
8. Add page-level headings to all pages

### MEDIUM (Next Sprint)
1. KnowledgeGraph floods trace API — add pagination
2. Shift+Enter for newline in chat
3. Confirmation before delete
4. LINE quick reply buttons
5. Human-readable model names
6. Wire concepts endpoint

### LOW (Backlog)
1. Dark mode support
2. Version consistency ("Synapse v3" → v4)
3. ErrorBoundary inline styles → Tailwind
4. Touch target sizes → 44px minimum
5. LINE /stats label fix
6. LINE Thai-native system prompt

## Summary
| Category | Critical | High | Medium | Low |
|----------|----------|------|--------|-----|
| Accessibility | 4 | 2 | 0 | 1 |
| Correctness | 1 | 2 | 2 | 1 |
| Visual/Design | 1 | 1 | 1 | 2 |
| Interaction/UX | 0 | 3 | 2 | 0 |
| LINE Bot | 1 | 3 | 1 | 2 |
| Code Quality | 1 | 1 | 1 | 0 |
| **Total** | **8** | **12** | **7** | **6** |
