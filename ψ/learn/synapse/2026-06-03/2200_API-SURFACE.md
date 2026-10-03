# Synapse v4 — API Surface (2026-06-03)

## HTTP API (FastAPI, port 8420)

All endpoints under `/api/` prefix. JSON request/response.

### Knowledge Operations
| Method | Path | Body | Returns |
|--------|------|------|---------|
| POST | /search | {query, scope?, tags?, mode?, limit?} | [{id, title, content, score, tags, ...}] |
| POST | /push | {title, content, doc_type?, tags?, ...} | {id, status, tags} |
| POST | /webhook | (HMAC-signed) | same as push |
| POST | /line-webhook | (LINE format) | {answered, created, pushed, ...} |
| POST | /supersede | {old_id, new_content, reason?} | {id, old_id, status} |
| POST | /trace | {source_id, target_id, relation, confidence?} | {id, source_id, target_id, relation} |
| GET | /get/{doc_id} | - | {id, title, content, tags, concepts, ...} |
| GET | /list | ?scope=&tags=&limit=&order= | [{id, title, ...}] |
| GET | /scopes | - | [{scope, count}] |
| GET | /tags | ?search=&limit= | [{name, count}] |
| GET | /concepts | ?search=&limit= | [{name, count}] |
| GET | /stats | - | {total_docs, active, superseded, ...} |
| POST | /trace-chain | {doc_id, direction?, max_depth?} | [{id, title, relation, ...}] |

### Project Management
| Method | Path | Body | Returns |
|--------|------|------|---------|
| POST | /register | {project_path, project_name?} | {project_name, status} |
| POST | /unregister | {project_name} | {project_name, status} |
| GET | /projects | - | [{project_name, project_path}] |
| POST | /search-cross | {query, scopes, limit?, mode?} | [{id, title, score, ...}] |

### Ingest & Maintenance
| Method | Path | Body | Returns |
|--------|------|------|---------|
| POST | /init | {path, tags?} | {total_files, indexed, duplicates, ...} |
| POST | /reconcile | {scope?, dry_run?} | {defrag: {...}, detox: {...}} |
| POST | /scan | - | {scanned_projects, results} |
| GET | /reconcile-log | ?limit= | [{id, scope, status, ...}] |

### Health
| Method | Path | Returns |
|--------|------|---------|
| GET | /health | {pg, qdrant?, embedding?} |
| GET | /health/live | {status: "alive"} |
| GET | /health/ready | {pg, qdrant, embedding} |

### Search Topics
| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | /search-topics | ?scope= | [{id, topic, source, ...}] |
| POST | /search-topics | {scope?, topic, source?, frequency?} | {id, topic, status} |
| DELETE | /search-topics/{id} | - | {status} |
| POST | /search-topics/{id}/toggle | {enabled} | {id, enabled} |
| POST | /search-topics/run | {limit?} | {topics_checked, indexed, ...} |

### Obsidian
| Method | Path | Body | Returns |
|--------|------|------|---------|
| POST | /write-to-obsidian | {doc_id? OR query?, vault_path?, subdir?} | {written, files, ...} |

### LLM Chat
| Method | Path | Body | Returns |
|--------|------|------|---------|
| POST | /chat | {message, scope?, tags?, model?} | StreamingResponse (text/plain) |

### Models
| Method | Path | Returns |
|--------|------|---------|
| GET | /models | [{name, size, modified_at}] |

## MCP Tools (15)

| Tool | Input | Returns |
|------|-------|---------|
| synapse_search | {query, scope?, tags?, doc_type?, oracle?, source_project?, concepts?, limit?, mode?} | [{id, title, content, score, tags, ...}] |
| synapse_push | {title, content, doc_type?, tags?, source_file?, source_project?, concepts?, oracle_name?, brain_path?, brain_tier?} | {id, status, tags} |
| synapse_supersede | {old_id, new_content, new_title?, reason?} | {id, old_id, status} |
| synapse_trace | {source_id, target_id, relation, confidence?} | {id, source_id, target_id, relation} |
| synapse_trace_chain | {doc_id, direction?, max_depth?, relation?} | [{id, title, relation, ...}] |
| synapse_concepts | {search?, limit?} | [{name, count}] |
| synapse_get | {doc_id} | {id, title, content, tags, concepts, ...} |
| synapse_scope | - | [{scope, count}] |
| synapse_stats | - | {total_docs, active, superseded, ...} |
| synapse_list | {scope?, tags?, limit?, order?} | [{id, title, ...}] |
| synapse_register | {project_path, project_name? OR scope?} | {project_name, status} |
| synapse_unregister | {project_name OR scope} | {project_name, status} |
| synapse_projects | - | [{project_name, project_path}] |
| synapse_search_cross | {query, scopes, limit?, mode?} | [{id, title, score, ...}] |
| synapse_write_to_obsidian | {doc_id? OR query?, vault_path?, subdir?} | {written, files, ...} |
| synapse_ingest_session | {title, content, doc_type?, tags?, source_project?, oracle_name?, concepts?} | {id, status, tags, tag_rule_actions?} |
| synapse_reconcile_log | {limit?} | [{id, scope, status, ...}] |
