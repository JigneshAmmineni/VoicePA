"""Fixed helper for the /daily-planner skill (allowlisted in .claude/settings.json).

Usage:
  python scripts/planner.py snapshot   # compact planning context from all state files
  python scripts/planner.py launch     # ensure dashboard server is running, open browser

`snapshot` exists so the planner doesn't have to read ~2500 lines of JSON into
context every morning; it prints only the fields planning decisions need.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
DASH_URL = f"http://127.0.0.1:{os.environ.get('DASH_PORT', '7789')}"


def read(name, default):
    try:
        with open(STATE / name, encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def snapshot():
    print("=== TODAY ===", date.today().isoformat())

    tasks = read("tasks.json", [])
    archive = read("tasks_archive.json", [])
    all_ids = [t["id"] for t in tasks + archive if str(t.get("id", "")).startswith("t")]
    nxt = max((int(i[1:]) for i in all_ids), default=0) + 1
    print("=== NEXT TASK ID ===", f"t{nxt:03d}", "(max across tasks.json + tasks_archive.json)")
    print("=== ACTIVE TASKS (todo/in_progress/waiting) ===")
    for t in tasks:
        if t.get("status") in ("todo", "in_progress", "waiting"):
            print(f"{t['id']}|{t['status']}|{t.get('tier')}|p:{t.get('priority')}|u:{t.get('urgency')}"
                  f"|{t.get('effort')}|{t.get('time_needed')}|due:{t.get('due_date')}|sched:{t.get('scheduled_date')}"
                  f"|ref:{t.get('ref')}|{t.get('title','')[:80]}")

    h = read("habits.json", {"habits": [], "log": {}})
    print("=== HABITS (active list) ===")
    print(", ".join(x.get("name", "") for x in h.get("habits", [])))
    print("=== HABIT LOG (last 8 days) ===")
    for d in sorted(h.get("log", {}), reverse=True)[:8]:
        print(d, [(e.get("habit"), e.get("status")) for e in h["log"][d]])

    p = read("priorities.json", {"priorities": []})
    print("=== PRIORITIES (active) ===")
    for x in p.get("priorities", []):
        if not x.get("resolved_at"):
            print(f"{x['id']}|{x['title']}|{x.get('note')}|ref:{x.get('ref')}")

    today = read("today.json", {})
    print("=== TODAY.JSON ===", "date:", today.get("date"),
          "| tasks:", [t.get("id") for t in today.get("tasks", [])])

    i = read("ideas.json", {"ideas": []})
    print("=== IDEAS (active/exploring/raw) ===")
    for x in i.get("ideas", []):
        if x.get("status") not in ("dead", "shelved"):
            print(f"{x['id']}|{x['status']}|{x.get('created_at')}|{x.get('title','')[:60]}")

    r = read("research.json", {"research": []})
    print("=== RESEARCH (reading/want-to-read) ===")
    for x in r.get("research", []):
        if x.get("status") in ("reading", "want-to-read"):
            print(f"{x['id']}|{x['status']}|{x.get('title','')[:60]}")


def restart():
    """Stop the running server (if any) and start a fresh one.

    Required after editing dashboard/server.py — `launch` deliberately no-ops when the
    port is taken, so without this the old process keeps serving stale code silently.
    """
    try:
        req = urllib.request.Request(DASH_URL + "/api/shutdown", data=b"{}",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=2)
        print("stopped running server")
        time.sleep(1)
    except Exception:
        print("no running server to stop")
    launch()


def launch():
    try:
        urllib.request.urlopen(DASH_URL + "/api/ping", timeout=1)
        # Already serving — and in VoicePA that server is the thing running this agent,
        # so the dashboard is open in front of the user. Opening another tab is the bug.
        print("server already running")
        return
    except Exception:
        # The agent runs this with system python (the allowlist is `python scripts/*`),
        # but the server needs the project venv. Prefer it; fall back to whatever is running us.
        venv_w = ROOT / ".venv" / "Scripts" / "pythonw.exe"
        own_w = Path(sys.executable).with_name("pythonw.exe")
        exe = str(venv_w if venv_w.exists() else own_w if own_w.exists() else sys.executable)
        subprocess.Popen(
            [exe, str(ROOT / "dashboard" / "server.py")],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
        time.sleep(1)
        print("server started")
    os.startfile(DASH_URL)
    print("opened", DASH_URL)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "snapshot":
        snapshot()
    elif cmd == "launch":
        launch()
    elif cmd == "restart":
        restart()
    else:
        sys.exit("usage: planner.py snapshot|launch|restart")
