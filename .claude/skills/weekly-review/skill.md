---
name: weekly-review
description: "Personal Assistant: Weekly review. Habit streaks, work reflection, stale tasks, and priority recalibration."
---

# weekly-review

Weekly check-in to reflect on the past week, assess habit consistency, and recalibrate `priorities.json` for the week ahead. Run every Sunday (or whenever the recurring task surfaces).

**This is a reflection ritual, not a planning system.** There is no weekly rhythm, no category targets, and no `weekly.json`. The week's direction lives entirely in `priorities.json`, which this review ends by updating.

## What this skill does

1. **Read state** — `state/tasks.json`, `state/tasks_archive.json` (for the week's completions), `state/habits.json`, `state/priorities.json`, and `state/journal.json`.
2. **Habit analysis** — Compute streaks and completion rates for the past 7 days.
3. **Work reflection** — Summarize tasks completed, tasks procrastinated, and overall output.
4. **Stale task audit** — Surface tasks that haven't moved in over 7 days.
5. **Journal review** — If there are journal entries from the past week, read them in two passes:
   - **Directional signals:** scan for language about focus, feeling behind, needing to pivot, or wanting to prioritize something differently (e.g. "need to buckle down on job search", "feeling stuck on X", "should go harder on Y this week"). Surface these explicitly before the general reflection, with a prompt: "On [date] you wrote: '[entry]' — sounds like a directional signal. Want to reflect this in your priorities?" Let the user's response feed directly into step 6.
   - **General reflections:** surface remaining entries as open reflection prompts.
6. **Priorities recalibration** — the point of the review. Walk the active priorities in order:
   - **Still top of mind?** If the underlying thing is done (linked task completed, deadline passed, problem solved), propose setting `resolved_at` and confirm.
   - **Anything to add?** Use the journal signals, the stale-task audit, and the completed-task list to propose additions. Don't invent priorities the user didn't signal.
   - **Is the order still right?** The first entry is THE most pressing thing. Ask if anything should move up or down.
   - **Enforce the cap:** 5 active max, aim for 3. If an addition would exceed it, ask which one it displaces. If everything is a priority, nothing is.

   Present the proposed list in full, get an explicit yes, then write `priorities.json` — fresh Read immediately before the write.
7. **Schedule the next review** — Add next week's weekly-review task to `tasks.json`, due the following Sunday.

## Weekly review format

```
## Weekly Review — [DATE RANGE]

### Habit Report
| Habit | Stage | 7-day streak | Completion rate | Status |
|-------|-------|-------------|-----------------|--------|
| ...   | ...   | ...         | ...             | solid / building / struggling |

**Habits to watch:** [any building habits missed 3+ days — suggest scaling back target]

### Work Done This Week
- Completed: [list of done tasks]
- In progress: [list of in_progress tasks]

### Procrastination Report
[Tasks that were due this week but got bumped repeatedly — call them out by name, no mercy]

### Stale Tasks
[Tasks untouched for 7+ days — surface with original due date if set. Ask: still relevant? cancel, reprioritize, or keep?]

### Journal Highlights

**Directional signals:**
[Entries that suggest a focus shift, feeling behind, or wanting to reprioritize — surfaced as explicit questions that feed into the priorities recalibration]

**Reflections:**
[Remaining entries as open reflection prompts]

### Direction Check
[1-2 sentence honest assessment: did this week's work actually serve the active priorities, or did it drift? Reference the user's long-term goals from memory if a goals note exists.]

### Priorities for Next Week
[The current active list, each with a proposed action: keep / resolve / reorder / add. Then the one question: "Does this look right?"]
```

## Rules
- Compute streaks from habits.json log. A streak = consecutive days with done or partial. A miss breaks it.
- Completion rate = days with done or partial / 7.
- "Solid" = active stage OR building with 5+/7 days. "Building" = building stage, 3-4/7. "Struggling" = building stage, <3/7.
- For struggling building habits, explicitly suggest reducing the target — consistency beats ambition.
- The procrastination report should be honest but not cruel. One observation, not a lecture.
- Never write `priorities.json` without an explicit yes on the proposed list. It is only ever edited through conversation.
- After the review, add the next weekly-review task to `tasks.json` (due following Sunday).
