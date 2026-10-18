"""PreToolUse/PostToolUse hook: enforce fresh-read-before-write on state/ files.

CLAUDE.md's hard rule is "always Read a state file immediately before editing it."
That rule is unenforceable by prose alone — a read from twenty turns ago looks
identical to a read from this turn, and the dashboard server writes these files
concurrently. This hook makes it mechanical:

  PostToolUse  on Read            -> record the file's mtime
  PreToolUse   on Edit/Write      -> deny if the mtime changed, or was never recorded

Only files under state/ are guarded; everything else passes through untouched.

Wired up in .claude/settings.json. Reads the hook payload as JSON on stdin and
writes a decision as JSON on stdout (an empty object means "allow").
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
RECORD = ROOT / "logs" / ".read_mtimes.json"


def guarded(path_str):
    """True if this path is a state file we care about."""
    if not path_str:
        return None
    try:
        p = Path(path_str).resolve()
        p.relative_to(STATE)
    except (ValueError, OSError):
        return None
    return p


def load_records():
    try:
        return json.loads(RECORD.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_records(records):
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    tmp = RECORD.with_suffix(".tmp")
    tmp.write_text(json.dumps(records), encoding="utf-8")
    os.replace(tmp, RECORD)


def mtime(p):
    try:
        return p.stat().st_mtime_ns
    except OSError:
        return None


def deny(reason):
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return  # malformed payload: stay out of the way

    event = data.get("hook_event_name")
    tool = data.get("tool_name")
    path = guarded((data.get("tool_input") or {}).get("file_path"))
    if path is None:
        return

    key = str(path)

    if event == "PostToolUse" and tool == "Read":
        records = load_records()
        records[key] = mtime(path)
        save_records(records)
        return

    if event == "PreToolUse" and tool in ("Edit", "Write", "NotebookEdit"):
        seen = load_records().get(key)
        now = mtime(path)
        if now is None:
            return  # new file, nothing to go stale
        if seen is None:
            deny(
                f"{path.name} has not been read in this session. CLAUDE.md requires a "
                f"fresh Read immediately before editing a state file. Read it, then retry."
            )
        elif seen != now:
            deny(
                f"{path.name} changed on disk after you read it — the dashboard server "
                f"or another session wrote to it. Editing now would clobber that change. "
                f"Read it again, then retry."
            )


if __name__ == "__main__":
    main()
