"""Delete this project's Claude Code session transcripts that have been idle for N days.

Claude Code keeps one JSONL per session under ~/.claude/projects/<encoded project path>/.
The cutoff is computed from the clock each time this runs, so there is nothing to inject:
`python scripts/purge_sessions.py` always means "idle for 30+ days as of right now".

  python scripts/purge_sessions.py             # delete transcripts idle for 30+ days
  python scripts/purge_sessions.py --days 7    # a shorter window
  python scripts/purge_sessions.py --dry-run   # list what would go, delete nothing

Age is the file's last-modified time, which Claude Code bumps on every turn. The script
never touches the memory/ folder that lives next to the transcripts, and never deletes
the session state/.session_id points at, however old it is.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
# Claude Code names the folder after the project path with every non-alphanumeric
# character replaced by "-": C:\Users\x\VoicePA -> C--Users-x-VoicePA
TRANSCRIPTS = Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(PROJECT))
SESSION_FILE = PROJECT / "state" / ".session_id"


def current_session():
    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8")).get("session_id")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=30, help="delete transcripts idle this many days or more (default 30)")
    ap.add_argument("--dry-run", action="store_true", help="list what would be deleted, delete nothing")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if not TRANSCRIPTS.is_dir():
        sys.exit(f"no transcript folder at {TRANSCRIPTS}")
    now = datetime.now()
    cutoff = now - timedelta(days=a.days)
    keep = current_session()
    print(f"{TRANSCRIPTS}\ncutoff {cutoff:%Y-%m-%d %H:%M}  ({a.days} days before now)")

    old = []
    for f in sorted(TRANSCRIPTS.glob("*.jsonl")):
        last = datetime.fromtimestamp(f.stat().st_mtime)
        if last < cutoff and f.stem != keep:
            old.append((f, last))
    if not old:
        print("nothing idle that long.")
        return
    verb = "would delete" if a.dry_run else "deleting"
    for f, last in old:
        print(f"  {verb}  {f.name}  last active {last:%Y-%m-%d}  ({(now - last).days} days, {f.stat().st_size // 1024} KB)")
        if not a.dry_run:
            f.unlink()
    print(f"{len(old)} transcript(s) {'listed' if a.dry_run else 'deleted'}.")


if __name__ == "__main__":
    main()
