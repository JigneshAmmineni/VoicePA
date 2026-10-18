---
name: wrap-up
description: "Personal Assistant: End-of-day wrap-up. Summarizes the day, flushes completions, resets today.json, and optionally captures a journal entry."
---

# wrap-up

End-of-day routine for the personal assistant. Run this before bed or when done for the day.

## What this skill does

1. **Read state** — Read `state/today.json`, `state/tasks.json`, and `state/habits.json`. The dashboard may have already marked tasks done and habits complete during the day — treat the current file state as truth, not the morning plan.
2. **Summarize the day** — Present a structured end-of-day overview (see format below)
3. **Handle incomplete tasks** — Split incomplete tasks from today's plan into two lists:
   - **Scheduled/due today/overdue** — tasks whose `scheduled_date` or `due_date` was today or prior to today and weren't completed. Note that these are now overdue.
   - **Picked up by the planner** — tasks the daily planner selected based on priority, with no `scheduled_date`/`due_date` forcing them today.

   Default action for every task in both lists is to leave it as-is — do NOT auto-change due dates and do NOT ask what to do with each one individually. Present both lists, then in that same message ask a single combined question covering both whether anything on the list actually got done and whether anything should be done differently with any of them (cancel, reschedule, etc) — one turn, not two separate follow-ups. Only touch a task if the user explicitly calls it out.
4. **Flush habit completions** — Confirm with the user any remaining habits before flushing. Don't overwrite existing log entries for today.
5. **Optional journal entry** — Ask: "Anything worth jotting down for the weekly review?" If yes, append a dated journal entry to `state/journal.json`, **verbatim** — never paraphrased.
6. **Reset today.json** — Clear today.json to an empty state with tomorrow's date.

## End-of-day summary format

```
## Wrap-up — [DATE]

### ✅ Done today
- [completed tasks]

### ⬜ Didn't get to
**Scheduled/due today (now overdue):**
- [tasks]

**Picked up by the planner (not due/scheduled today):**
- [tasks]

(Default: left as-is unless you flag otherwise.)

### Habits
- [habit name]: done / partial (X/Y) / missed
- streak info if relevant

### Low-hanging fruit
[Any quick tasks (S effort, <30m) still in the backlog that could've been done today — surface 1-2 max, don't pile on]

### Journal
[If user provided a note, show it here. Otherwise skip this section.]
```

## today.json reset format

```json
{
  "date": "YYYY-MM-DD",
  "habits": ["habit name", ...],
  "tasks": [],
  "notes": ""
}
```

Habits list is copied fresh from `habits.json` active list. Tasks start empty — tomorrow's plan gets built during the next day's planning session.

## Rules
- Never delete tasks — only update `due_date` if the user explicitly says to move it.
- Never auto-bump due dates — overdue is a valid and intentional state.
- Never modify past log entries in habits.json.
- The journal entry is optional — don't force it. One sentence is fine.
- Be warm but honest in the summary. Call out a good day when it was one. Call out a wasted day too — gently, not brutally.
