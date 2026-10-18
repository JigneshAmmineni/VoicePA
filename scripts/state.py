"""Safe CRUD for the state/ JSON files (allowlisted in .claude/settings.json).

Use this instead of ad-hoc python for adding or updating entries — it computes the
next id correctly (checking the archive for tasks), refuses silent duplicates, and
writes atomically so it can't clobber the dashboard server mid-write.

  python scripts/state.py next-id watchlist
  python scripts/state.py add watchlist --from payload.json
  python scripts/state.py add watchlist --json "{\"title\": \"...\"}"
  python scripts/state.py set tasks t184 --set status=done
  python scripts/state.py show tasks t184
  python scripts/state.py show tasks --ref pj002       # every task for a project/idea/paper
  python scripts/state.py show tasks --ids t184,t177   # status of specific tasks, one line each

If this script can't answer a question about a state file, extend it — do not fall
back to an improvised `python -c` snippet.
  python scripts/state.py archive          # sweep done/cancelled tasks -> tasks_archive.json

Editing an entry's long prose (notes, review) is still fine with the Edit tool —
this exists for the operations that need computed ids or whole-file rewrites.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / "state"


def path_for(name):
    p = STATE / (name if name.endswith(".json") else name + ".json")
    if not p.exists():
        sys.exit(f"no such state file: {p.name}")
    return p


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def save(path, data):
    """Atomic write — temp file in the same dir, then os.replace."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def container(data):
    """Return the list of entries, whatever the file's wrapper shape is."""
    if isinstance(data, list):
        return data
    lists = [v for v in data.values() if isinstance(v, list)]
    if len(lists) == 1:
        return lists[0]
    sys.exit("cannot locate the entry list in this file")


# id prefix + date field for files that are still empty (nothing to infer from)
NEW_FILE_DEFAULTS = {
    "tasks": ("t", "created_at"),
    "ideas": ("i", "created_at"),
    "projects": ("pj", "created_at"),
    "research": ("r", "added_at"),
    "priorities": ("p", "added_at"),
    "shopping": ("s", "added_at"),
    "watchlist": ("w", "added_at"),
}


def stem(name):
    return name[:-5] if name.endswith(".json") else name


def id_parts(entries, name):
    """Infer the id prefix and width from existing entries, e.g. ('t', 3)."""
    for e in entries:
        m = re.match(r"^([a-zA-Z]+)(\d+)$", str(e.get("id", "")))
        if m:
            return m.group(1), len(m.group(2))
    if stem(name) in NEW_FILE_DEFAULTS:
        return NEW_FILE_DEFAULTS[stem(name)][0], 3
    sys.exit(f"cannot infer id format for {name} — no existing ids")


def next_id(name):
    """Next id across the file and, for tasks, its archive."""
    entries = container(load(path_for(name)))
    pool = list(entries)
    if name.startswith("tasks"):
        arch = STATE / "tasks_archive.json"
        if arch.exists():
            pool += container(load(arch))
    prefix, width = id_parts(pool, name)
    nums = [int(m.group(1)) for m in
            (re.match(rf"^{prefix}(\d+)$", str(e.get("id", ""))) for e in pool) if m]
    return f"{prefix}{max(nums, default=0) + 1:0{width}d}"


def cmd_next_id(args):
    print(next_id(args.file))


def cmd_add(args):
    if args.json:
        entry = json.loads(args.json)
    elif getattr(args, "from_file", None):
        entry = json.loads(Path(args.from_file).read_text(encoding="utf-8-sig"))
    else:
        sys.exit("provide --json or --from")

    path = path_for(args.file)
    data = load(path)
    entries = container(data)

    title = entry.get("title") or entry.get("name")
    if title and not args.force:
        dupes = [e for e in entries
                 if str(e.get("title") or e.get("name") or "").lower() == str(title).lower()]
        if dupes:
            sys.exit(f"duplicate: {dupes[0].get('id')} already has that title (use --force to add anyway)")

    entry["id"] = next_id(args.file)
    if any("created_at" in e for e in entries):
        date_field = "created_at"
    elif any("added_at" in e for e in entries):
        date_field = "added_at"
    else:
        date_field = NEW_FILE_DEFAULTS.get(stem(args.file), (None, "added_at"))[1]
    entry.setdefault(date_field, date.today().isoformat())

    entries.append(entry)
    save(path, data)
    print(f"added {entry['id']} to {path.name}")


def coerce(v):
    if v == "null":
        return None
    if v in ("true", "false"):
        return v == "true"
    return v


def cmd_set(args):
    path = path_for(args.file)
    data = load(path)
    entry = next((e for e in container(data) if e.get("id") == args.id), None)
    if entry is None:
        sys.exit(f"{args.id} not found in {path.name}")
    for pair in args.set or []:
        if "=" not in pair:
            sys.exit(f"bad --set {pair!r}, expected field=value")
        k, v = pair.split("=", 1)
        print(f"{args.id}.{k}: {entry.get(k)!r} -> {coerce(v)!r}")
        entry[k] = coerce(v)
    for pair in args.append or []:
        if "=" not in pair:
            sys.exit(f"bad --append {pair!r}, expected field=text")
        k, v = pair.split("=", 1)
        existing = entry.get(k)
        if existing is not None and not isinstance(existing, str):
            sys.exit(f"cannot append to {k}: not a string")
        entry[k] = (existing + " " + v) if existing else v
        print(f"{args.id}.{k}: appended {len(v)} chars (now {len(entry[k])})")
    if not (args.set or args.append):
        sys.exit("provide --set or --append")
    save(path, data)


def summary_line(e):
    """Compact one-line view: id | status | due | title."""
    bits = [str(e.get("id")), str(e.get("status", ""))]
    if e.get("due_date"):
        bits.append("due:" + e["due_date"])
    if e.get("scheduled_date"):
        bits.append("sched:" + e["scheduled_date"])
    if e.get("ref"):
        bits.append("ref:" + e["ref"])
    bits.append(str(e.get("title") or e.get("name") or "")[:70])
    return " | ".join(bits)


def cmd_show(args):
    entries = container(load(path_for(args.file)))
    if args.ref:
        entries = [e for e in entries if e.get("ref") == args.ref]
    if args.status:
        wanted = {s.strip() for s in args.status.split(",") if s.strip()}
        entries = [e for e in entries if e.get("status") in wanted]
    if args.ids:
        wanted = [i.strip() for i in args.ids.split(",") if i.strip()]
        found = {e.get("id"): e for e in entries}
        for i in wanted:
            print(summary_line(found[i]) if i in found
                  else f"{i} | NOT FOUND in {stem(args.file)} (archived or wrong id?)")
        return
    if args.id:
        entry = next((e for e in entries if e.get("id") == args.id), None)
        if entry is None:
            sys.exit(f"{args.id} not found")
        print(json.dumps(entry, indent=2, ensure_ascii=False))
        return
    if not entries:
        print(f"no matching entries in {stem(args.file)}")
        return
    for e in entries:
        print(summary_line(e))


def cmd_log(args):
    """Show the `log` block of habits.json for a date (default today)."""
    data = load(path_for(args.file))
    log = data.get("log") if isinstance(data, dict) else None
    if log is None:
        sys.exit(f"{stem(args.file)} has no log block")
    if args.days:
        for d in sorted(log, reverse=True)[:args.days]:
            print(d, "|", format_log(log[d]))
        return
    day = args.date or date.today().isoformat()
    print(day, "|", format_log(log.get(day, [])) or "(nothing logged)")


def format_log(entries):
    out = []
    for e in entries:
        if isinstance(e, dict):
            out.append(f"{e.get('habit')}={e.get('status')}"
                       + (f" ({e['progress']})" if e.get("progress") else ""))
        else:
            out.append(str(e))
    return ", ".join(out)


def cmd_archive(args):
    tp, ap = path_for("tasks"), path_for("tasks_archive")
    tasks, archive = load(tp), load(ap)
    move = [t for t in tasks if t.get("status") in ("done", "cancelled")]
    if not move:
        print("nothing to archive")
        return
    have = {t.get("id") for t in archive}
    clash = [t["id"] for t in move if t["id"] in have]
    if clash:
        sys.exit(f"id collision with archive: {clash}")
    archive.extend(move)
    save(ap, archive)
    save(tp, [t for t in tasks if t.get("status") not in ("done", "cancelled")])
    print(f"archived {len(move)}: {', '.join(t['id'] for t in move)}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("next-id"); p.add_argument("file"); p.set_defaults(fn=cmd_next_id)

    p = sub.add_parser("add")
    p.add_argument("file")
    p.add_argument("--json")
    p.add_argument("--from", dest="from_file")
    p.add_argument("--force", action="store_true", help="allow a duplicate title")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("set")
    p.add_argument("file"); p.add_argument("id")
    p.add_argument("--set", action="append", metavar="FIELD=VALUE")
    p.add_argument("--append", action="append", metavar="FIELD=TEXT",
                   help="append text to an existing string field (e.g. notes)")
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("show")
    p.add_argument("file"); p.add_argument("id", nargs="?")
    p.add_argument("--ref", help="only entries whose ref matches, e.g. pj002")
    p.add_argument("--ids", help="comma-separated ids, compact one line each")
    p.add_argument("--status", help="comma-separated statuses, e.g. todo,in_progress,waiting")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("log")
    p.add_argument("file", help="habits")
    p.add_argument("date", nargs="?", help="YYYY-MM-DD (default today)")
    p.add_argument("--days", type=int, help="instead, show the N most recent logged days")
    p.set_defaults(fn=cmd_log)

    p = sub.add_parser("archive"); p.set_defaults(fn=cmd_archive)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
