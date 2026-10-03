# Document Type Guidelines

> Constitution for Synapse — how AI classifies, stores, and manipulates knowledge.

## Two Families

All documents fall into exactly one of two families:

| Family | Nature | Has dates? | Has status? | Archiveable? |
|--------|--------|-------------|--------------|--------------|
| **Content-based** | Know, understand, remember | `created_at`, `updated_at`, `archived_at` | No status lifecycle | Yes — archive when no longer relevant |
| **Event-based** | Do, happen, pay, track | Multiple date fields in metadata | Yes — pending → done/cancelled | No — completed or cancelled, never archived |

---

## Content-based Types (รู้ เข้าใจ จำ)

No expiration date. No "done" status. Archive when no longer relevant.

### knowledge
A lesson learned that can be reused.
- **Metadata**: `{brain_tier, source, confidence}`
- **Can become**: `pattern`, `reference`
- **Example**: "Mock tests catch hidden bugs when external services are None"

### note
Captured but not yet classified. The default type.
- **Metadata**: `{origin, media_type}`
- **Can become**: anything (knowledge, idea, todo, good-to-know)
- **Example**: A LINE message that hasn't been categorized yet

### idea
A new thought that hasn't been validated yet.
- **Metadata**: `{status: spark|validating|abandoned, related_to}`
- **Can become**: `todo`, `knowledge`, `not-to-do`
- **Example**: "What if we made a habit tracker with Thai calendar?"

### insight
A moment of clarity — understanding that shifts perspective.
- **Metadata**: `{trigger, emotion, session_id}`
- **Can become**: `knowledge`, `pattern`
- **Example**: "บำเพ็ญเพียร์ is not about reaching the destination — it's about becoming the person who walks"

### moment
An experience worth remembering. Not knowledge — a feeling.
- **Metadata**: `{location, emotion, media_ids}`
- **Can become**: `insight`, `knowledge`
- **Example**: "Sunrise on the mountain — felt peace"

### good-to-know
Useful information for later, not needed right now.
- **Metadata**: `{applicable_context, source, expires: false}`
- **Can become**: `knowledge`, `reference`
- **Example**: "This restaurant is closed on Mondays"

### reference
An external source being cited.
- **Metadata**: `{url, author, year, source_type}`
- **Can become**: `knowledge`
- **Example**: "Vannevar Bush, As We May Think, 1945"

### retro
A retrospective — looking back at a session or period.
- **Metadata**: `{session_date, friction_points, week_number}`
- **Can become**: `knowledge` (lessons extracted)
- **Example**: "Session retro: fixed auth bug, learned about asyncpg jsonb codec"

### pattern
A recurring pattern recognized across multiple experiences.
- **Metadata**: `{frequency, examples, confidence}`
- **Can become**: `wisdom`
- **Example**: "Every time we skip integration tests, something breaks in prod"

### protocol
A rule or procedure to follow.
- **Metadata**: `{enforcement: strict|advisory, scope}`
- **Can become**: `instinct` (internalized)
- **Example**: "Never push --force to main"

### instinct
Deeply internalized knowledge — part of identity.
- **Metadata**: `{brain_tier: intrinsic, origin}`
- **Cannot become anything else** — this is terminal
- **Example**: "Nothing is deleted — supersede only"

### wisdom
Distilled truth from years of experience.
- **Metadata**: `{origin, years_valid}`
- **Cannot become anything else** — terminal
- **Example**: "The best code is code you don't write"

### handoff
Knowledge passed from one person/session to another.
- **Metadata**: `{from_session, to_session, urgency}`
- **Can become**: `knowledge` (after recipient acknowledges)
- **Example**: "Server password is in vault — rotate on Monday"

### log
A chronological record of events.
- **Metadata**: `{log_type, duration, outcome}`
- **Can become**: `retro` (when reviewed)
- **Example**: "Deploy v3.2 at 14:30 — successful, 2min downtime"

---

## Event-based Types (ทำ เกิด จ่าย ตาม)

Have dates, have status lifecycle, may trigger alerts.

### todo
Something to do with a deadline.
- **Metadata**: `{due_date, status: pending|in_progress|done|cancelled, priority: urgent|high|medium|low, assignee}`
- **Auto-action**: Creates `scheduled_tasks` row when `due_date` is set
- **Can become**: `knowledge` (lesson from completing), `not-to-do` (decided not to)
- **Example**: "Submit report before Friday"

### not-to-do
Something explicitly forbidden — an anti-pattern or rule.
- **Metadata**: `{reason, learned_from, severity: critical|high|medium}`
- **Cannot become anything else** — this is terminal (a rule, not a task)
- **Example**: "Never git push --force to main"

### reminder
A nudge at a specific time.
- **Metadata**: `{remind_at, recurrence: once|daily|weekly|monthly, channel: line|dm}`
- **Auto-action**: Creates `scheduled_tasks` row + alert at `remind_at`
- **Can become**: `todo` (when it becomes actionable)
- **Example**: "Call mom on Sunday"

### event
Something that already happened — a record.
- **Metadata**: `{occurred_at, duration_min, attendees, location, category}`
- **Can become**: `knowledge` (lessons extracted)
- **Example**: "Team meeting 2h — decided on v3 launch date"

### payment
Money going out or coming in.
- **Metadata**: `{amount, currency, paid_date, due_date, payee, category, receipt_url}`
- **Auto-action**: Creates `scheduled_tasks` row when `due_date` is set and `paid_date` is null
- **Can become**: `event` (once paid)
- **Example**: "Electricity bill 1,500 THB due June 15"

### deadline
A hard delivery date with consequences.
- **Metadata**: `{due_date, status: on_track|at_risk|blocked, blockers, deliverable}`
- **Auto-action**: Creates `scheduled_tasks` row + escalation alerts
- **Can become**: `event` (when delivered), `knowledge` (lessons)
- **Example**: "v3 launch June 30"

---

## Type Transition Rules (รูป และ สุญญตา)

One document can become another via **supersession** (never deletion):

```
note ──→ knowledge     (classified after reflection)
note ──→ todo          (realized it needs action)
note ──→ good-to-know  (recognized as useful-later)
idea ──→ todo           (decided to act on it)
idea ──→ not-to-do     (decided NOT to act)
idea ──→ abandoned     (abandoned idea)
todo ──→ knowledge     (completed → lesson learned)
todo ──→ not-to-do     (decided not to do)
reminder ──→ todo       (became actionable)
event ──→ knowledge    (lessons extracted)
payment ──→ event      (paid → recorded)
deadline ──→ knowledge (post-mortem lessons)
```

### Transition Process

1. Create new document with new `doc_type` + updated `metadata`
2. Set old document's `superseded_by` to new document's ID
3. Old document remains searchable but marked as superseded
4. New document inherits `tags` and `concepts` from old (can modify)

### Archiving (Content-based only)

Content-based documents can be archived when no longer relevant:
- Set `archived_at = NOW()` — document stays in DB but is excluded from default search
- Archived documents are still findable with explicit `archived=true` filter
- This is NOT deletion — Principle 1: Nothing is Deleted

---

## Namespace Tags

Tags use `namespace:value` format for structured classification:

| Namespace | Purpose | Examples |
|-----------|---------|---------|
| `platform` | Source platform | `platform:line`, `platform:discord`, `platform:claude` |
| `person` | People involved | `person:doctorboyz`, `person:team-a` |
| `topic` | Subject matter | `topic:health`, `topic:devops`, `topic:finance` |
| `project` | Project origin | `project:synapse`, `project:emily-oracle` |
| `oracle` | Oracle source | `oracle:synapse`, `oracle:dev-oracle` |
| `type` | Sub-classification | `type:bug`, `type:feature`, `type:security` |
| `priority` | Urgency | `priority:urgent`, `priority:high` |

### Tag Rules

When a tag matches a `tag_rules` entry, the handler auto-classifies:
- `type:task` → creates `scheduled_tasks` row
- `priority:urgent` → sets alert_on_due
- `platform:line` → routes replies via LINE

---

## Auto-actions by doc_type

| doc_type | Auto-action | Condition |
|----------|------------|-----------|
| `todo` | Create `scheduled_tasks` | `metadata.due_date` is set |
| `reminder` | Create `scheduled_tasks` + alert | `metadata.remind_at` is set |
| `payment` | Create `scheduled_tasks` | `metadata.due_date` is set AND `metadata.paid_date` is null |
| `deadline` | Create `scheduled_tasks` + escalation | `metadata.due_date` is set |
| `note` | Guided question flow | Content is short or ambiguous (via tag_rules) |

---

## Search and Filter

### Default search (excludes archived and superseded)

```sql
WHERE superseded_by IS NULL AND archived_at IS NULL
```

### Find archived content

```sql
WHERE archived_at IS NOT NULL
```

### Find event-based with pending status

```sql
WHERE doc_type IN ('todo', 'deadline', 'payment')
  AND metadata->>'status' = 'pending'
  AND superseded_by IS NULL
```

### Find content by tag namespace

```sql
WHERE tags @> '["platform:line"]'
```

### Find overdue tasks

```sql
WHERE doc_type IN ('todo', 'deadline', 'payment')
  AND (metadata->>'due_date')::timestamptz < NOW()
  AND (metadata->>'status') IN ('pending', 'in_progress')
```