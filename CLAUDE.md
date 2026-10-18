# VoicePA — Project Instructions

A personal assistant you talk to. There is no application code here beyond the
dashboard — the assistant operates by reading and writing state files under `state/`.

**Design principle:** This folder is the control plane, not the workspace. State files
are lightweight references and pointers — summaries, links, paths, statuses. Actual work
artifacts (research dumps, docs, code, plans) live elsewhere. Keep entries lean.

**Hard rule — fresh read before every write:** Always Read a state file immediately
before editing it, in the same turn as the edit. Never write from memory of an earlier
read, no matter how recent it feels. The dashboard server and other sessions write to
these files concurrently, so remembered content may be stale. A `PreToolUse` hook
enforces this mechanically by comparing file mtime at read time against write time, but
the rule applies whether or not the hook catches you.

**Hard rule — use `scripts/state.py`, never ad-hoc Python.** Adding an entry, changing a
field, or archiving is done with the script below, not an improvised `python -c`
snippet. It computes ids correctly (checking `tasks_archive.json`), blocks duplicate
titles, and writes atomically so it can't corrupt a file the dashboard is reading.

```bash
python scripts/state.py next-id tasks                       # next id, archive-aware
python scripts/state.py add watchlist --from payload.json   # append (id + date auto-filled)
python scripts/state.py set tasks t184 --set status=done    # change fields
python scripts/state.py show tasks t184                     # one entry, or omit id to list
python scripts/state.py show tasks --ref pj002              # every task linked to a project/idea/paper
python scripts/state.py show tasks --ids t184,t177          # status of specific tasks, one line each
python scripts/state.py archive                             # sweep done/cancelled tasks out of tasks.json
```

Write the payload with the Write tool to `tmp/payload.json` in the project root and pass
that relative path to `--from` (never an absolute Windows path: Bash strips the backslashes
and the script gets `C:UsersyouAppData...`); `--json '<inline>'` works for small entries. The Edit tool is
still the right call for revising long prose in an existing entry (`notes`, `review`) —
always after a fresh Read.

**Housekeeping, only when the user asks:** `python scripts/purge_sessions.py` deletes this
project's Claude Code session transcripts idle for 30+ days, cutoff computed from the clock
at run time (`--days N` to change it, `--dry-run` to list without deleting).

**If the script can't answer a question, extend the script** — never fall back to an
improvised `python -c`, and never pipe the script's output into one to reformat it. A
missing capability is a one-time edit to `scripts/state.py`, not a recurring hand-rolled
snippet.

**Run script commands bare.** `scripts/` is allowlisted (`Bash(python scripts/*)`), but
permission rules match the *whole* command string as a prefix — so wrapping the call in
`cd ...`, a variable assignment, or a pipe defeats the match and triggers a needless
prompt. The working directory is already the project root: just
`python scripts/state.py ...` with full paths inline.

**Spoken replies are capped.** The final message is read aloud: at most two sentences,
thirty words. Say only what changes what the user does next; anything empty or unchanged
goes unsaid. No closing question or offer. Long output goes to the state files and the
dashboard, never the voice.

---

## State Files

### `state/tasks.json`

The full task backlog. Each entry is a one-time task with metadata.

```json
{
  "id": "t001",
  "title": "string",
  "tier": "short | medium | long",
  "priority": "high | medium | low",
  "urgency": "high | medium | low",
  "effort": "S | M | L | XL",
  "time_needed": "e.g. 30m, 2h, half-day",
  "category": "e.g. career, school, personal, project",
  "due_date": "YYYY-MM-DD or null",
  "scheduled_date": "YYYY-MM-DD or null",
  "status": "todo | in_progress | waiting | done | cancelled | hibernation",
  "notes": "string or null",
  "ref": "i001 | pj001 | r001 | null",
  "created_at": "YYYY-MM-DD"
}
```

**Field guide:**
- `tier`: short = due within days, medium = weeks/months, long = ongoing goals
- `priority` vs `urgency`: a task can be high priority but low urgency (important, not
  time-sensitive) or low priority but high urgency (deadline-driven but not critical)
- `effort`: rough size — S (<30m), M (30m–2h), L (2–4h), XL (4h+)
- `scheduled_date`: optional hard scheduling. If it is today, the task is always
  included in the day's plan. If it is in the future, the task is excluded entirely
  until that date. If it is in the past (missed), it surfaces as overdue. Setting or
  changing this also triggers Calendar sync — see below.
- `calendar_event_id`: optional. The Google Calendar event id created for this task's
  `scheduled_date`. Set automatically when the event is created; used to update or
  remove the event later. Null or absent means no event exists yet.

**Rules:**
- Source of truth for all tasks. Never delete entries — set `status` to `cancelled`.
- `hibernation` is for tasks worth preserving with no intention of working on them soon
  — a dormant backlog. Never surface hibernation tasks in daily planning unless asked.
- `waiting` is for tasks blocked on something outside the user's control — a callback, a
  form response, someone else's action. Not `todo` (not actionable yet) and not
  `hibernation` (waiting tasks are often high-priority, just temporarily un-actionable).
  - **Notes convention:** start `notes` with `WAITING ON: <condition>`.
  - **Planning behavior:** a waiting task is not focus work — don't count it toward the
    day's workload. But unlike hibernation it is NOT hidden: surface it in the daily
    plan as a follow-up reminder, flagged as waiting, distinct from the actionable list.
  - **`scheduled_date` is reinterpreted** for waiting tasks: it is a check-back date, not
    a do-it-today date. Surface it when that date is today, when `due_date` is near or
    passed, or when it has been waiting a long time with no movement. A waiting task
    with no dates still gets an occasional "still waiting on X?" nudge.
  - **Lifecycle:** when the blocker clears, flip status back to `todo`/`in_progress`.
- When adding a task, always read `tasks.json` first to find the highest existing id,
  then increment. Never guess the last id from context. **Also check the highest id in
  `tasks_archive.json`** — completed tasks get archived, so the newest id may live there.
- `state/tasks_archive.json` holds `done` and `cancelled` tasks moved out of
  `tasks.json` to keep it lean (same schema, flat list). Sweep periodically. Archived
  tasks are the historical record — never delete from the archive.
- When a task is moved to `today.json`, it stays in both.
- `ref` is optional — links a task to an idea (`i001`), project (`pj001`), or research
  entry (`r001`).

**Calendar sync for scheduled tasks:**

Whenever a task gets a `scheduled_date` set or changed, place a matching event on Google
Calendar for that date — regardless of `due_date`. This gives the day a real
time-blocked shape instead of a floating to-do.

1. **Idempotency first.** Before creating anything, check `calendar_event_id`. If set,
   update that event instead of making a new one. Write the returned id back when
   creating. Never create a second event for the same task.
2. **Duration.** Derive from `time_needed`; if absent, fall back to `effort`
   (S→30m, M→1h, L→2h, XL→3h). For a range, use the upper bound.
3. **Time-of-day placement.**
   - **Intellectually taxing** work (engineering, learning, research, writing, anything
     needing deep focus) → earlier in the day (~9:00–12:00), when the brain is fresh.
   - **Throwaway / low-focus** work (admin, errands, quick checks — the kind of thing
     doable while listening to music) → afternoon or evening.
   - Break ties with `priority`/`urgency`: higher goes earlier within its band.
4. **Work around what's already on the calendar** — always read that day's full agenda
   first (`gws calendar +agenda`), then place the task using real judgment, the way a
   thoughtful human assistant would. Look at *every* event on the day and reason about
   what each actually demands. The cases below are illustrative, not exhaustive:
   - **Passive / long / low-attention events** (watching a game, a long block that's
     just a reminder to do a simple thing): the new task **may overlap** it.
   - **Focus-demanding events** (calls, meetings, interviews — anything needing prep or
     presence): do **not** place the task before or during it. Schedule it **after** the
     event ends, so prep time and the event stay protected. Never wedge a taxing or
     prep-heavy task into the run-up to such an event.
   - **Events at a physical location**: account for **travel time both ways plus a
     buffer**. Treat the whole out-of-house span as blocked.
   - **Back-to-back or tightly packed days:** leave breathing room. A reasonable gap
     between commitments is not free real estate.
   - Don't stack two focus tasks on the same slot — sequence them.
   - When the day is genuinely full, place the task in the best available slot and flag
     the tightness rather than forcing a bad fit. The goal is a schedule the user can
     actually follow, not a perfectly packed grid.
5. **Event content.** Title = task title. Description = task id (e.g. `t178`) plus any
   key note, for traceability.
6. **Lifecycle.** When a scheduled task is completed, cancelled, hibernated, or its
   `scheduled_date` changes, update or remove the corresponding event to match. A
   future-dated event for a task that's no longer active should not linger.
7. **Write policy — auto-create (user opted in).** Create/update the calendar event
   automatically, without asking first. This is a standing exception to the usual
   per-action GWS-write confirmation, granted specifically for scheduled-task sync.
   Validate with `--dry-run` when unsure. After creating, **always state explicitly**:
   the exact time scheduled, and whether it overlaps or sits near any existing events
   that day (name them). The user will say if they want it moved — don't ask
   preemptively.

---

### `state/habits.json`

Recurring daily habits and their completion history.

```json
{
  "habits": [
    { "name": "habit name", "stage": "active | building", "group": "morning | daily | night" }
  ],
  "log": {
    "YYYY-MM-DD": [
      { "habit": "habit name", "status": "done | partial", "progress": "e.g. 40/100 or null" }
    ]
  }
}
```

**Field guide:**
- `stage`: "active" = locked in, treat misses normally. "building" = still forming, be
  encouraging not harsh about misses.
- `status`: "done" = fully completed, "partial" = some progress but not finished.
- `progress`: optional string for quantified habits (e.g. "40/100"). Null for binary.
- `group`: optional display grouping for the dashboard's habit panel (chronological
  routine order). Habits without a group render ungrouped at the end.

**Rules:**
- `habits` is the active list. Add or remove habits without touching the log.
- Each day's log entry is a list of habit objects. Absence from the list = missed.
- When marking habits done or partial, append to (or create) today's log entry.
  **Always use the current date from context as the log key** — do not infer it from
  prior log entries.
- Never modify past log entries unless explicitly asked to correct a mistake.

**Streak tracking:**
- When surfacing habits, compute streaks from the log.
- A streak = consecutive days with at least a `partial` or `done` entry. A miss breaks it.
- Surface streaks visibly — "5 day streak" is motivating. For `building` habits,
  acknowledge any streak warmly, even if it's 1.

**Planning nudge rules:**
- When planning the day, check the last 7 days for each habit.
- If a `building` habit has been missed more than 3 of the last 7 days, flag it —
  suggest scaling back the target rather than white-knuckling the same goal.
- Don't overload the day plan with habits the user hasn't been hitting.
  Consistency > ambition.

---

### `state/today.json`

Today's focused plan. Populated each morning from tasks + habits.

```json
{
  "date": "YYYY-MM-DD",
  "habits": ["habit name"],
  "tasks": [
    { "id": "t001", "title": "string", "time_needed": "string", "priority": "high | medium | low" }
  ],
  "notes": "string"
}
```

**Rules:**
- `habits` is copied from the `habits.json` active list each day.
- `tasks` contains only the tasks selected for today (short snippets, not full metadata
  — source of truth stays in `tasks.json`).
- At end of day: flush habit completions to `habits.json`, mark completed tasks `done`
  in `tasks.json`, then reset `today.json` to empty.
- If `today.json` has a date older than today, treat it as stale and offer to reset it.

---

### `state/priorities.json`

The short list of what matters most *right now* — themes that override normal task
sorting. **This is the primary driver of what to work on day to day.** Not a second task
list.

```json
{
  "priorities": [{
    "id": "p001",
    "title": "string — short theme name",
    "note": "string or null — one line of context / next concrete step",
    "ref": "tXXX | iXXX | rXXX | null",
    "added_at": "YYYY-MM-DD",
    "resolved_at": "YYYY-MM-DD or null"
  }]
}
```

**Rules:**
- **Hard cap: 5 active entries** (`resolved_at: null`); aim for 3. If the user adds a
  sixth, ask which one it displaces. If everything is a priority, nothing is.
- Order matters — the first active entry is THE most pressing thing. Keep the array
  sorted by importance.
- Never delete — set `resolved_at` when done or no longer top-of-mind.
- Update on phrases like "X is the most important thing right now", "the priority this
  week is X", "X is handled". Infer resolution when the underlying thing completes
  (e.g. a linked task is done) and confirm.
- **Scope of influence (deliberately narrow):** active priorities are pinned at the top
  of the dashboard, shown at the top of the daily plan, and tasks related to an active
  priority get surfaced first when planning the day. That is all. It must not drive
  anything else: no scheduling, no calendar events, no status changes.
- Only edited through conversation — no skill, script, or server mutates this file as a
  side effect.

---

### `state/journal.json`

Optional end-of-day notes captured during wrap-up. Surfaced during weekly review.

```json
{ "entries": [ { "date": "YYYY-MM-DD", "note": "string" } ] }
```

**Rules:**
- Append only. Never edit or delete past entries.
- One entry per day max. If one exists for today, append to the note rather than
  creating a duplicate.
- Entries are optional — only created if the user provides a note.
- **Journal entries must be recorded verbatim.** Do not summarize, paraphrase, clean up,
  or reword what the user says. Copy the exact text as given.

---

### `state/research.json`

All research being tracked — papers, frameworks, open source projects — in one flat list.

```json
{
  "research": [{
    "id": "r001",
    "title": "string",
    "type": "paper | framework | open source",
    "authors": "string or null",
    "link": "string or null",
    "workspace": "string or null — Notion page, GitHub repo, or wherever active work lives",
    "status": "want-to-read | reading | done | shelved",
    "notes": "string or null",
    "added_at": "YYYY-MM-DD"
  }]
}
```

**Rules:**
- Auto-generate next id in sequence (r001, r002, ...).
- `type` is optional but descriptive — use it when the distinction matters.
- Never delete entries — set `status` to `shelved` instead.
- Surface active entries (status: reading) during daily planning when relevant.

---

### `state/ideas.json`

Business ideas, project concepts, and anything worth capturing.

```json
{
  "ideas": [{
    "id": "i001",
    "title": "string",
    "description": "string",
    "category": "e.g. business, project, research, product",
    "status": "raw | exploring | active | shelved | dead",
    "notes": "string or null",
    "created_at": "YYYY-MM-DD"
  }]
}
```

**Rules:**
- Low friction — capture fast, metadata can be sparse for raw ideas.
- Never delete entries — set `status` to `dead` instead.
- `active` means there's a corresponding task in `tasks.json` driving it forward.
- An idea is a *concept* — a business, product, or research pitch. Once something is
  just a thing being built with no product ambition, it belongs in `projects.json`.

---

### `state/projects.json`

Things being built. Anything spanning multiple tasks that isn't a business/product idea
(`ideas.json`) or a research topic (`research.json`) — tools, toy projects, automations,
side builds, one-off experiments.

```json
{
  "projects": [{
    "id": "pj001",
    "title": "string",
    "description": "string",
    "category": "e.g. tool, toy, automation, infra, personal",
    "status": "planned | active | paused | done | shelved",
    "workspace": "string or null — repo, folder, or Notion page where the work lives",
    "notes": "string or null",
    "created_at": "YYYY-MM-DD"
  }]
}
```

**Field guide:**
- `status`: `planned` = intend to build, nothing started. `active` = being worked.
  `paused` = started, deliberately on hold. `done` = finished/shipped (a real terminal
  state, unlike ideas). `shelved` = abandoned.
- `workspace`: where the actual artifacts live — this folder stays a control plane.

**Rules:**
- Never delete entries — set `status` to `shelved` instead.
- Tasks link to a project through `ref` (`pj001`), same as ideas and research.
- Scope test: a business/product pitch → `ideas.json`. A paper/framework to read →
  `research.json`. Something built for its own sake → here. A project may start life as
  an idea; when it becomes a build, create a project entry and leave the idea entry as
  its origin (don't move or delete it — task `ref`s point at the idea id).

---

### `state/shopping.json`

Running list of things to buy, return, and sell.

```json
{
  "items": [{
    "id": "s001",
    "name": "string",
    "type": "buy | return | sell",
    "category": "e.g. clothing, health, personal, tech, groceries",
    "priority": "high | medium | low",
    "vendor": "string or null — store or platform",
    "notes": "string or null",
    "expected_date": "YYYY-MM-DD or null — for ordered items, when delivery is expected",
    "deadline": "YYYY-MM-DD or null",
    "status": "todo | ordered | returning | needs_packaging | listed | received | done",
    "added_at": "YYYY-MM-DD"
  }]
}
```

**Field guide:**
- `type`: `buy` = something to purchase. `return` = something being sent back.
  `sell` = something to list and sell.
- `status` by type:
  - **buy:** `todo` → `ordered` (set `expected_date`) → `received`
  - **return:** `returning` (set `deadline` for the return window) → `needs_packaging`
    (needs packaging and physically taking to a store/post office) → `done`
  - **sell:** `todo` (need to list) → `listed` → `needs_packaging` (sold, needs
    shipping) → `done`
- `deadline` on a buy = last day to purchase before a sale or offer expires. On
  `returning`/`needs_packaging` = last day to ship.

**Rules:**
- Auto-increment id (s001, s002, ...).
- Never delete entries — terminal states are `received` (buys kept) and `done`.
- Surface `todo`, `ordered`, `returning`, `listed` and `needs_packaging` items when the
  user asks what they need to do.
- Flag any `deadline` within 3 days proactively.

---

### `state/watchlist.json`

Movies, shows, YouTube series, documentaries to watch.

```json
{
  "items": [{
    "id": "w001",
    "title": "string",
    "type": "movie | show | documentary | anime | anime movie | youtube | other",
    "year": "YYYY",
    "genre": ["string"],
    "runtime": "string — e.g. '~2h', '~30 min/ep, 8 eps'",
    "vibe": ["string — mood tags"],
    "notes": "string or null — brief plot summary or notable context",
    "progress": "string or null — e.g. 'S2E4', '~1h 2m'. Update when pausing mid-watch.",
    "rating": "string or null — e.g. '9/10'. Fill after watching.",
    "review": "string or null — personal thoughts after watching.",
    "status": "unwatched | watching | watched",
    "added_at": "YYYY-MM-DD"
  }]
}
```

**Rules:**
- Auto-increment id (w001, w002, ...).
- Never delete entries — set `status` to `watched` when done.
- When adding any entry, do targeted web searches to fill in `genre`, `runtime`, and
  `vibe` — don't leave them null.
- `vibe` is a list of mood tags. Use consistent tags so mood-based filtering works:
  `light`, `feel-good`, `funny`, `dark`, `gritty`, `tense`, `thought-provoking`,
  `emotional`, `chill`, `anxiety-inducing`, `chaotic`, `heartwarming`.
- When the user asks for something for a specific mood ("something light", "something
  gritty"), filter by `vibe` tags and recommend from `unwatched` entries.
- Surface on demand, or during wrap-up if the user wants a wind-down rec.

---

## Google Workspace Access

Authenticated via the `gws` CLI (`gws auth login`), as whichever Google account the user
authorized. `gws auth status` shows which.

| Service | Tool | Common uses |
|---|---|---|
| Gmail | `gws gmail` | Read emails, summarize newsletters, draft replies |
| Calendar | `gws calendar` | Check upcoming events, add events, plan the day |
| Google Docs | `gws docs` | Read and write documents |
| Google Drive | `gws drive` | Browse and manage files |
| Google Sheets | `gws sheets` | Read and write spreadsheets |

**Rules:**
- Always read before writing to any Google resource.
- Never send emails or post calendar events without explicit confirmation. The one
  standing exception is scheduled-task calendar sync, described under `tasks.json`.
- Gmail: `gws gmail +triage` for an inbox summary, `gws gmail +read` to read a message.
- Calendar: `gws calendar` to check events before planning the day.
- Always use `--fields` to limit response fields and avoid large JSON blobs flooding
  context (e.g. `--fields "files(id,name,mimeType)"`).
- Use `--dry-run` before any mutating operation to validate the payload first.
- If unsure about a payload structure, run `gws schema <resource>.<method>` first.
- Use `--page-all` for paginated list operations; output is NDJSON.

---

## Tone & Behavior

<!-- TODO: written by the user. -->

---

## Notes on what is deliberately absent

- **No rhythm system.** Day-to-day focus comes from `priorities.json`, not from weekly
  category targets. There is no `weekly.json`, no `rhythm_category` on any entry, and no
  session logging.
- **No "Common Interactions" lookup table.** The schemas above are the single source of
  truth for each file's behavior. Re-add a table only if natural-language mapping
  measurably suffers.
- **No dashboard documentation here.** The dashboard is described in its own README.
- Daily planning, weekly review and wrap-up behavior live in `.claude/skills/`, not in
  this file. CLAUDE.md loads every session; skills load on demand.
