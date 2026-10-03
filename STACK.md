# Synapse v4 — Technology Stack

> PostgreSQL Single Source of Truth — pgvector replaces Qdrant

## Core Stack

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Language | Python | 3.12+ | Core application |
| Framework | FastAPI | 0.115+ | HTTP API + LINE webhook |
| ASGI Server | Uvicorn | 0.34+ | Production server |
| Database | PostgreSQL + pgvector | 17 / pg17 | Single source of truth — documents, vectors, FTS |
| Vector Extension | pgvector | 0.4+ | Vector(768) embeddings, cosine similarity, IVFFlat index |
| Embedding | Ollama (nomic-embed-text) | latest | 768-dim local embeddings |
| LLM (primary) | OpenRouter | — | gemini-2.0-flash-001 (chat), deepseek-chat-v3-0324 (summary) |
| LLM (fallback) | Ollama (qwen2.5:7b) | latest | Local LLM for when OpenRouter unavailable |
| LINE | LINE Messaging API | v2 | Chatbot webhook, reply, push |
| MCP | MCP SDK | 1.0+ | stdio server for Claude Code integration |

## Key Libraries

| Library | Purpose |
|---------|---------|
| asyncpg | PostgreSQL async driver |
| pgvector | Python client for pgvector extension |
| httpx | HTTP client (LINE API, OpenRouter, external requests) |
| pydantic | Settings management + data validation |
| pyyaml | Config hot-reload |
| beautifulsoup4 | HTML parsing for web ingest |
| pypdf | PDF extraction |
| python-docx | Word document extraction |
| youtube-transcript-api | YouTube transcript fetching |

## Infrastructure

| Component | Details |
|-----------|---------|
| Container | Docker (python:3.13-slim) |
| Database Image | pgvector/pgvector:pg17 |
| Orchestration | Docker Compose (shared with infra-oracle) |
| Deployment | Mac mini + OrbStack |

## Architecture Patterns

- **Single Store**: PostgreSQL handles documents, vectors, tags, traces, scheduling — no external vector DB
- **Hybrid Search**: FTS (tsvector) + Vector (pgvector cosine) merged via RRF in Python layer
- **Push Pipeline**: text → hash → dedup → chunk (if >1500 chars) → embed → store
- **Supersede, Never Delete**: Documents marked superseded_by, content preserved
- **Tag-based Filtering**: EXISTS subquery pattern avoids DISTINCT conflicts with vector ordering
