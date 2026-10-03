# Synapse v4 — Gate Configuration

> Phase gates for Synapse development lifecycle

## Gate Flow

```
Gate 0: discovery → scaffold
Gate 1: scaffold → implement
Gate 2: implement → stabilize
Gate 3: stabilize → graduate
```

## Gate 0: Discovery

### Base Checks (from ψ/gates/gate-0-discovery.md)
- [x] PRD.md exists with Vision, Roles, Architecture
- [x] Problem statement clear
- [x] Target users identified (LINE users, Oracle fleet, developer)

### Project-Specific Additions
- [x] LINE bot requirements documented
- [x] pgvector migration plan (from v3 Qdrant)

## Gate 1: Scaffold

### Base Checks
- [x] Build succeeds (`pip install -e .`)
- [x] STACK.md exists
- [x] Docker Compose configured
- [x] Environment variables documented (.env.example)

## Gate 2: implement → stabilize (CURRENT)

### Base Checks (from ψ/gates/gate-2-implement.md)
- [ ] All tests pass
- [ ] Lint: 0 errors
- [ ] Security: 0 critical/high
- [ ] Test coverage ≥ 80%

### Project-Specific Additions
- [x] LINE bot: all commands work (/ask, /search, /tags, /recent, /stats, /help)
- [x] LINE bot: auto-ingest works (text, image OCR, location)
- [x] LINE bot: group/room silent mode
- [x] LINE bot: source display includes tags
- [x] Docker health check green (pg: true, embedding: true)
- [x] No Qdrant references in src/
- [x] pgvector: push, search, embed all working
- [x] Hybrid search: FTS + vector RRF merge
- [ ] PRD updated for v4 (Qdrant → pgvector)
- [ ] 17 integration tests fixed (PG connection in CI)

## Gate 3: stabilize → graduate

### Base Checks
- [ ] All security items resolved
- [ ] Documentation complete
- [ ] Production deployment verified
- [ ] Monitoring/alerting configured
- [ ] Backup/restore tested

### Project-Specific Additions
- [ ] Chunking for long documents
- [ ] Tag assistant infrastructure (tag_rules, scheduled_tasks, alert_log)
- [ ] Claude ingest pipeline replacement
- [ ] Rate limiting on API
- [ ] LINE bot error rate < 1%

## Gate Skipped

_(none)_
