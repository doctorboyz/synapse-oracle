# Synapse v4 — Security

> LINE tokens, API keys, and database credentials — handling and protection

## Secret Management

All secrets via environment variables (docker/.env in production):

| Secret | Env Var | Scope |
|--------|---------|-------|
| Database URL | `DATABASE_URL` | postgresql://user:pass@host:5432/synapse |
| LINE Channel Secret | `LINE_CHANNEL_SECRET` | HMAC-SHA256 webhook verification |
| LINE Access Token | `LINE_CHANNEL_ACCESS_TOKEN` | Bot reply + media download |
| OpenRouter API Key | `OPENROUTER_API_KEY` | LLM chat + OCR |
| Ollama URL | `OLLAMA_URL` | Local embeddings (no auth) |

## Rules

1. **Never commit `.env`** — docker/.env is gitignored. Only docker/.env.example is committed.
2. **Validate at startup** — Settings validates required vars, raises clear errors if missing.
3. **Rotate on exposure** — If a token appears in logs, rotate immediately.

## Webhook Security

- LINE signature verification via `HMAC-SHA256` (line_handler.py:verify_line_signature)
- Request body validated against `x-line-signature` header
- Rejects unverified requests with 403

## API Security

- All endpoints use FastAPI dependency injection
- Input validation via pydantic models
- No authentication on internal API (port 8420, localhost-only in production)

## Input Validation

- LINE messages: text length check (>10 chars to skip noise)
- API push: doc_type validated against whitelist
- File ingest: size limits, type checking
- URL validation: local-only enforcement for internal endpoints

## Data Protection

- **Nothing is deleted**: Supersede pattern preserves all content history
- **Content hashing**: SHA-256 dedup prevents duplicate storage
- **No user PII in knowledge store**: LINE user IDs are truncated in tags

## Security Checklist

- [x] No hardcoded secrets in source
- [x] Secrets in gitignored .env file
- [x] LINE webhook signature verification
- [x] Input validation on all endpoints
- [x] Parameterized SQL queries (asyncpg)
- [x] No raw SQL string concatenation
- [x] Content dedup prevents storage abuse
- [ ] Rate limiting on API endpoints (not yet)
- [ ] Authentication on management endpoints (not yet)
- [ ] Audit logging for sensitive operations (not yet)
