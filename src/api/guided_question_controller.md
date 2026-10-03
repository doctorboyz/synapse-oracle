# Guided Question Controller

> State machine for guided document collection via LINE Quick Reply.
> One controller — code reads this, humans reference this.

## Architecture

```
User sends content → AI detects type → enter state machine
  ↓
Step 0: Confirm doc_type (note/task/learning)
  ↓
Step 1-N: Collect type-specific required fields
  ↓
Step N+1: Confirm all → store + apply tag_rules
  ↓
User can say "พอ" (done) anytime → store what we have
User can say "ยกเลิก" (cancel) anytime → discard
```

## Quick Reply Convention

Every step has 2-4 quick reply buttons. Last button is always "พอแล้ว" (enough).
First button is always the most likely/positive answer.

## State Machine Per Document Type

---

### TYPE: note

Knowledge note — general information, observations, facts.

| Step | Field | Question (TH) | Quick Replies | Validation |
|------|-------|---------------|---------------|------------|
| 0 | type_confirm | "นี่คือบันทึกความรู้ทั่วไปใช่ไหม?" | [`✅ ใช่`, `📋 เป็น Task`, `📚 เป็น Learning`, `❌ ยกเลิก`] | `ใช่`→step1, `Task`→switch(task), `Learning`→switch(learning) |
| 1 | tags | "อยากเพิ่ม tag อะไรบ้าง? (พิมพ์มาเลย)" | [`📝 ทั่วไป`, `💡 ไอเดีย`, `🔗 อ้างอิง`, `พอแล้ว`] | free text or button |
| 2 | concepts | "มีแนวคิดหลักอะไรบ้าง?" | [`#general`, `#observation`, `#reference`, `พอแล้ว`] | free text or button |
| 3 | confirm | "บันทึกตามนี้?" | [`✅ บันทึก`, `✏️ แก้ไข`, `❌ ยกเลิก`] | `บันทึก`→store |

**Required**: content (≥10 chars)
**Auto-tags**: `note`, source platform tag

---

### TYPE: task

Actionable task — needs due date, priority, assignee.

| Step | Field | Question (TH) | Quick Replies | Validation |
|------|-------|---------------|---------------|------------|
| 0 | type_confirm | "นี่คืองานที่ต้องทำใช่ไหม?" | [`✅ ใช่`, `📝 เป็น Note`, `📚 เป็น Learning`, `❌ ยกเลิก`] | `ใช่`→step1 |
| 1 | due_date | "กำหนดเสร็จเมื่อไหร่?" | [`📅 วันนี้`, `📅 พรุ่งนี้`, `📅 สัปดาห์หน้า`, `📅 ยังไม่กำหนด`] | parse date or skip |
| 2 | priority | "ความสำคัญระดับไหน?" | [`🔥 ด่วน`, `🟡 ปกติ`, `🟢 ต่ำ`, `พอแล้ว`] | `ด่วน/ปกติ/ต่ำ` |
| 3 | assignee | "ใครรับผิดชอบ?" | [`🙋 ฉันเอง`, `👥 ยังไม่ระบุ`, `พอแล้ว`] | free text or button |
| 4 | confirm | "บันทึกตามนี้?" | [`✅ บันทึก`, `✏️ แก้ไข`, `❌ ยกเลิก`] | `บันทึก`→store |

**Required**: content (≥10 chars), due_date (can be null)
**Auto-tags**: `task`, source platform tag
**Post-store**: apply tag_rules → create scheduled_task

### Priority mapping
| Button | Value |
|--------|-------|
| 🔥 ด่วน | high |
| 🟡 ปกติ | medium |
| 🟢 ต่ำ | low |

### Due date parsing (from free text at step 1)
- `วันนี้` / `today` → today
- `พรุ่งนี้` / `tomorrow` → today+1
- `วันจันทร์`-`วันอาทิตย์` + `นี้`/`หน้า` → next occurrence
- `ภายใน N วัน` → today+N
- `dd/mm/yyyy` → parsed date
- `yyyy-mm-dd` → ISO date
- `ยังไม่กำหนด` / `no date` → null

---

### TYPE: learning

Learning/insight — needs concepts, source attribution.

| Step | Field | Question (TH) | Quick Replies | Validation |
|------|-------|---------------|---------------|------------|
| 0 | type_confirm | "นี่คือบทเรียนหรือความรู้ที่ได้เรียนรู้ใช่ไหม?" | [`✅ ใช่`, `📝 เป็น Note`, `📋 เป็น Task`, `❌ ยกเลิก`] | `ใช่`→step1 |
| 1 | concepts | "แนวคิดหลักคืออะไร? (พิมพ์หรือเลือก)" | [`#learned`, `#insight`, `#pattern`, `พิมพ์เอง...`] | at least 1 concept |
| 2 | source | "ที่มาของความรู้นี้?" | [`💬 สนทนา`, `📖 อ่าน`, `🔬 ทดลอง`, `🌐 อื่นๆ`] | free text or button |
| 3 | tags | "อยากเพิ่ม tag อะไรบ้าง?" | [`#lesson`, `#best-practice`, `#mistake`, `พอแล้ว`] | free text or button |
| 4 | confirm | "บันทึกตามนี้?" | [`✅ บันทึก`, `✏️ แก้ไข`, `❌ ยกเลิก`] | `บันทึก`→store |

**Required**: content (≥10 chars), concepts (≥1)
**Auto-tags**: `learning`, source platform tag

---

## Global Commands (valid at any step)

| User types | Action |
|------------|--------|
| `พอ` / `พอแล้ว` / `done` / `enough` | Store with current state, skip remaining steps |
| `ยกเลิก` / `cancel` / `ไม่` | Discard pending review |
| `ข้าม` / `skip` | Skip current field, move to next step |
| `แก้ไข` / `edit` | Go back to type selection (step 0) |

## State Storage

Extend `pending_reviews` with:
```sql
ALTER TABLE pending_reviews ADD COLUMN current_step INTEGER DEFAULT 0;
ALTER TABLE pending_reviews ADD COLUMN doc_type_confirmed TEXT;  -- note/task/learning
ALTER TABLE pending_reviews ADD COLUMN collected_fields JSONB DEFAULT '{}';
```

`collected_fields` accumulates user answers per step:
```json
{
  "due_date": "2026-05-30",
  "priority": "high",
  "assignee": "me",
  "tags": ["งาน", "ด่วน"],
  "concepts": ["deployment"]
}
```

## Step Transition Logic (Python pseudocode)

```python
STEPS_BY_TYPE = {
    "note": ["type_confirm", "tags", "concepts", "confirm"],
    "task": ["type_confirm", "due_date", "priority", "assignee", "confirm"],
    "learning": ["type_confirm", "concepts", "source", "tags", "confirm"],
}

def get_step_question(doc_type: str, step_index: int, collected: dict) -> tuple[str, list[dict]]:
    """Return (question_text, quick_reply_items) for current step."""
    steps = STEPS_BY_TYPE.get(doc_type, STEPS_BY_TYPE["note"])
    if step_index >= len(steps):
        return final_confirm_question(collected)
    
    step_name = steps[step_index]
    return STEP_QUESTIONS[doc_type][step_name](collected)

def apply_answer(doc_type: str, step_index: int, collected: dict, answer: str) -> dict:
    """Parse answer, validate, return updated collected_fields + next_step."""
    steps = STEPS_BY_TYPE.get(doc_type, STEPS_BY_TYPE["note"])
    step_name = steps[step_index]
    
    # Check global commands first
    if answer in ("พอ", "พอแล้ว", "done", "enough"):
        return {"done": True, "collected": collected}
    
    parsed = STEP_PARSERS[doc_type][step_name](answer)
    collected.update(parsed)
    
    next_step = step_index + 1
    if next_step >= len(steps):
        return {"done": True, "collected": collected}
    
    return {"done": False, "next_step": next_step, "collected": collected}
```

## Quick Reply Button Format (LINE API)

```python
def make_quick_reply(buttons: list[tuple[str, str]]) -> list[dict]:
    """Convert (label, text) pairs to LINE quick reply format.
    
    First button is primary (most likely answer).
    Last button is always ('พอแล้ว', 'พอแล้ว') unless it's the confirm step.
    """
    items = []
    for label, text in buttons:
        items.append({
            "type": "action",
            "action": {
                "type": "message",
                "label": label,
                "text": text,
            }
        })
    return items
```

## Validation Rules Per Field

| Field | Rule | Error Message |
|-------|------|---------------|
| due_date | Valid date format or skip keyword | "วันที่ไม่ถูกต้อง ลองใหม่ (เช่น พรุ่งนี้, 2026-05-30, วันศุกร์นี้)" |
| priority | Must be high/medium/low (map from TH) | "เลือก: ด่วน / ปกติ / ต่ำ" |
| tags | Comma-separated, max 10 | "ใช้ลูกน้ำคั่น เช่น: งาน, ด่วน, python" |
| concepts | Comma-separated, min 1, max 10 | "อย่างน้อย 1 แนวคิด เช่น: deployment, testing" |
| assignee | Any text or skip | (no validation — free text) |

## Future: Type Detection Hints

When `_should_ask_guided_questions` triggers, use content signals to pre-select type:
- Contains `@` mention → likely task
- Contains `due/deadline/ภายใน/กำหนด` → likely task  
- Contains `เรียนรู้/learn/บทเรียน/insight/pattern` → likely learning
- Contains `?` or question words → likely note (Q&A capture)
- Default → note

Pre-selected type is shown at step 0 — user confirms or changes.
