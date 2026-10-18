---
name: daily-planner
description: Plan the day. Reads priorities, tasks, habits, calendar, and emails to suggest what to do today and populate today.json. Trigger when user says "plan my day", "what should I do today", "daily plan", "morning briefing", or similar.
---

# Daily Planner

Generates a focused daily plan by synthesizing priorities, tasks, habits, calendar, and email. Writes the result to `state/today.json` and presents a clear summary.

**Priorities drive the day.** `state/priorities.json` is the primary signal for what to work on — tasks tied to an active priority outrank normal urgency/priority sorting, and the active priorities themselves are shown at the top of the plan. There is no weekly rhythm or category quota.

## Steps

### 1. Load context

Run the allowlisted snapshot script (no permission prompt) — it prints a compact extract of every state file so the full JSON never has to be read into context:

```bash
python scripts/planner.py snapshot
```

It covers: active tasks (todo/in_progress/waiting with all planning fields), habits + last 8 days of log, active priorities, today.json staleness, and active ideas/research. Use the Read tool on a specific state file only when a task's full `notes` are needed.

If auto-memory holds a long-term goals note, read it — it's the first principles for tie-breaking between otherwise-equal tasks.

### 2. Check the calendar

```bash
gws calendar +agenda
```

(No `--fields` flag — `+agenda` doesn't accept it. No pipes or redirects — the exact commands `gws calendar +agenda` and `gws gmail +triage` are allowlisted; decorating them re-triggers permission prompts.)

Filter for events scheduled today. Note any time blocks that are already committed — factor these into available time when selecting tasks.

### 3. Triage emails

```bash
gws gmail +triage
```

Scan emails from today and yesterday. Split output into three buckets:

**Bucket 1 — Action required (show these first, one line each):**
Flag anything that requires a real response or decision, regardless of sender type:
- Recruiting emails from real people or companies (referrals, interview requests, offer follow-ups, application status)
- Transactional alerts that need attention (refunds, billing issues, account flags, insurance, legal, government)
- Personal emails requiring a reply
- Anything with a deadline or expiry

**Bucket 2 — Job postings (consolidate into one line):**
Count job alert emails from automated sources (LinkedIn Job Alerts, Jobright, Handshake, Lensa, etc.) and collapse into a single bullet:
→ "X job posting emails from LinkedIn, Jobright, [sources] — check when ready"
Do NOT list individual job postings.

**Bucket 3 — Newsletters (subject lines only):**
For known newsletters (Daniel Miessler / Unsupervised Learning, ByteByteGo, TLDR, LinkedIn News, The Rundown, Morning Brew, etc.), just list the subject line. Do NOT open or read them. The user will ask to read specific ones separately if interested.

Ignore entirely: marketing, promotions, Spotify/Letterboxd/app notifications, automated digests with no actionable content.

### 4. Surface ideas and research worth flagging

Before selecting tasks, scan `ideas.json` and `research.json` for things that may deserve attention. **Don't do this every day** — only flag when:

- An idea with `status: raw | exploring | active` has **no linked task** in `tasks.json` (check via `ref` field) and has been sitting for a while (created more than ~2 weeks ago). Ask: "this idea has been untouched — want to work on it today or add a task?"
- A paper with `status: reading` has been in that state for a long time with no recent progress. Prompt gently.
- A paper with a venue deadline is coming up within ~4 weeks. Surface it proactively.

Keep it to 1–2 nudges max. If nothing qualifies, skip this section entirely — don't manufacture filler.

### 5. Select tasks for today

From `tasks.json`, filter `status: todo | in_progress` (this excludes `waiting`, `hibernation`, `done`, `cancelled`). Then apply the following logic in order:

**Waiting tasks (surface as reminders, not grind-work):**
- `waiting` tasks are blocked on something outside the user's control — don't put them in the actionable focus list or count them toward the day's workload.
- But DO surface them in the plan as follow-up reminders (flagged as waiting, distinct from the tasks to actually work). Surface a waiting task when: its `scheduled_date` (which for a waiting task means the **check-back / follow-up date**) is today; its `due_date` is near or passed; or it's been waiting a long time. A waiting task with no dates still gets an occasional "still waiting on X?" reminder.
- Phrase as a heads-up, e.g. "Reminder — still waiting on [the `WAITING ON:` condition] for [task]. Follow up, or find another route?" Seeing it is enough to prompt a follow-up or an alternative action.

**Scheduled-date enforcement (runs first, strict — applies to `todo`/`in_progress` tasks):**
- Any task with `scheduled_date` equal to today: **always include** — no exceptions, regardless of priority, effort, or time budget.
- Any task with `scheduled_date` in the future (after today): **always exclude** — do not surface, suggest, or factor into prioritization today.
- Any task with `scheduled_date` in the past (before today): treat as overdue — fold into normal priority logic at the top of the list, same as any other task with a missed due date.
- Tasks with no `scheduled_date` field (or `null`): proceed to normal priority logic below.

**Normal priority order (for tasks without a scheduled_date):**

1. **Overdue** — `due_date` is before today. These go first, no debate.
2. **Due within 2 days** — high urgency regardless of priority field.
3. **Linked to an active priority** — tasks whose `ref`, title, or notes clearly tie to an entry in `priorities.json`. Walk the priorities in order: the first active entry is THE most pressing thing, so its tasks come before the second's, and so on.
4. **High urgency + high priority** — the meat of the day.
5. **Low-hanging fruit** — effort `S` or `M` tasks that are short-term tier. Good for momentum.
6. **Long-term goal alignment** — when two tasks are otherwise equal, prefer the one that maps to the user's long-term goals.

**Don't overload:** Sum up `time_needed` across selected tasks. Leave breathing room — don't schedule more than ~6h of focused work. Account for calendar blocks.

**Tier rules:**
- `short` tasks: eligible any day
- `medium` tasks: include if they're approaching due_date or have been sitting too long
- `long` tasks: only include if the user has explicitly set one as in_progress, or if nothing else is pressing

### 6. Write today.json

```json
{
  "date": "YYYY-MM-DD",
  "habits": ["habit name", "..."],
  "tasks": [
    { "id": "tXXX", "title": "...", "time_needed": "...", "priority": "high|medium|low" }
  ],
  "notes": "Brief context: e.g. calendar blocks, email action items, anything the user should keep in mind"
}
```

- `habits` is always the full active list from `habits.json`
- `tasks` is only today's selected subset — keep it lean
- `notes` captures calendar conflicts, email flags, or any heads-up worth surfacing

### 7. Write dashboard.json + launch the dashboard

Write `state/dashboard.json` with the generated parts of the dashboard (everything else the server derives live from state files):

```json
{
  "date": "YYYY-MM-DD",
  "focus": "title of the top active priority, or null",
  "compyutah_line": "one deadpan line for the header — personality, current context, no filler",
  "agenda": [{ "time": "9:00–11:30 AM", "title": "event title" }],
  "emails": [{ "flag": "ACTION | ATTN", "from": "sender", "subject": "one line" }],
  "email_footnotes": ["12 job alerts (LinkedIn ×8, Indeed ×4) — collapsed", "3 newsletters — subject lines in chat"]
}
```

- `agenda` comes from step 2 (12-hour times, chronological). `emails` from step 3: bucket 1 → `ACTION`/`ATTN` entries; buckets 2–3 → one `email_footnotes` line each.
- Do **not** launch or open the dashboard. In VoicePA the dashboard server is what runs this session, so it is already open in front of the user; the page re-reads state on its own.

### 8. Present the plan

The plan lives in today.json and dashboard.json and the dashboard renders it. The spoken
reply is one sentence: only most consequential things today — a deadline, a
hard-scheduled event, an action-required email. If there is nothing in the inbox, don't even
mention the inbox, same goes for calendar, priorities, etc. Dont even mention something that
doesn't have a consequential note for that day. NEVER mention habits.
Do not enumerate sections. Do not mention lists that are empty.
