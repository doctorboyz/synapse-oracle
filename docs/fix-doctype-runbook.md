# Fix DocType Runbook

## Problem
The old LINE handler auto-classified regular messages as `doc_type="task"` when they contained dates, @mentions, or task-like words. These were never meant to be tasks.

## Solution

### Step 1: Preview (dry-run)

```bash
# See all task-type docs that would be changed
synapse fix-doctype

# Or filter by LINE source type
synapse fix-doctype --source-type line-user
synapse fix-doctype --source-type line-group
synapse fix-doctype --source-type line-room
```

### Step 2: Apply the fix

```bash
# Fix all LINE-sourced task docs → note
synapse fix-doctype --source-type line-user --apply
synapse fix-doctype --source-type line-group --apply
synapse fix-doctype --source-type line-room --apply

# Or fix ALL task docs (if you're sure none are real tasks)
synapse fix-doctype --apply
```

### Step 3: Verify

```bash
# Check no more task-type docs remain
synapse stats
synapse list --doc-type task
```

### API endpoint

```bash
# Dry-run
curl -X POST http://localhost:8420/api/fix-doctype \
  -H 'Content-Type: application/json' \
  -d '{"from_type": "task", "to_type": "note", "dry_run": true}'

# Apply
curl -X POST http://localhost:8420/api/fix-doctype \
  -H 'Content-Type: application/json' \
  -d '{"from_type": "task", "to_type": "note", "dry_run": false}'

# Filter by source
curl -X POST http://localhost:8420/api/fix-doctype \
  -H 'Content-Type: application/json' \
  -d '{"from_type": "task", "to_type": "note", "source_type": "line-user", "dry_run": false}'
```

### MCP tool

```
synapse_fix_doctype(from_type="task", to_type="note", dry_run=True)
```

## What gets fixed

1. **doc_type**: `task` → `note` for matching documents
2. **scheduled_tasks**: Any auto-created scheduled tasks linked to these docs are deleted
3. **doc_type**: Legacy `task` alias resolves to `todo` via oracle_paths validation

## New behavior (after fix)

| Input | Old behavior | New behavior |
|-------|-------------|-------------|
| "send report by Friday" | `doc_type="task"` | `doc_type="note"` |
| "see you 3/6" | `doc_type="task"` | `doc_type="note"` |
| "@john check this" | `doc_type="task"` | `doc_type="note"` |
| `/task send report by Friday` | N/A | `doc_type="todo"` |
| `/todo deploy app` | N/A | `doc_type="todo"` |
| `/remind call team Monday` | N/A | `doc_type="reminder"` |
