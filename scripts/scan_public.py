"""Scan a checkout's tracked text files for personal strings and secret shapes.

Personal terms (your name, email, employer, anything that identifies you) come from
private_terms.txt in the project root, one per line, matched case-insensitively. That
file is gitignored on purpose: the public branch must not carry the list of what it was
scrubbed of. Secret shapes and user-profile path markers are built in.

  python scripts/scan_public.py                   # this checkout
  python scripts/scan_public.py <folder>          # another checkout, e.g. the public worktree
  python scripts/scan_public.py --terms FILE ...  # a terms file somewhere else

Exits 1 on any hit, so sync_public.py can refuse to commit.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
BUILTIN = ["sk-ant-", "ya29.", "-----begin ", "refresh_token", "x-anthropic-billing",
           "\\users\\", "/c/users/"]
SHAPES = re.compile(r"AIza[0-9A-Za-z_-]{20,}|\b[0-9]{3}[-. ][0-9]{3}[-. ][0-9]{4}\b")
SKIP = {"uv.lock", "scripts/scan_public.py"}   # the lock file, and this file's own pattern list
# intentional occurrences: path -> lowercase substring that marks the allowed line
ALLOW = {"LICENSE": "copyright (c)", "scripts/purge_sessions.py": "users\\x\\"}


def load_terms(path):
    try:
        return [t.strip().lower() for t in Path(path).read_text(encoding="utf-8").splitlines()
                if t.strip() and not t.startswith("#")]
    except FileNotFoundError:
        return []


def scan(items, terms):
    """items: iterable of (path, bytes). Returns [(path, lineno, line)] for every hit."""
    needles = [t for t in BUILTIN + list(terms) if t]
    hits = []
    for path, data in items:
        path = path.replace("\\", "/")
        if path in SKIP:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue   # binary, e.g. the onnx models
        for n, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            if path in ALLOW and ALLOW[path] in low:
                continue
            if any(t in low for t in needles) or SHAPES.search(line):
                hits.append((path, n, line.strip()[:140]))
    return hits


def tracked(root):
    out = subprocess.run(["git", "ls-files", "-z"], cwd=str(root), capture_output=True, check=True).stdout
    for p in out.decode("utf-8").split("\0"):
        if p:
            yield p, (Path(root) / p).read_bytes()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=str(PROJECT), help="checkout to scan (default: this project)")
    ap.add_argument("--terms", default=str(PROJECT / "private_terms.txt"), help="personal terms file")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    terms = load_terms(a.terms)
    if not terms:
        print(f"note: no personal terms loaded from {a.terms}; built-in patterns only")
    hits = scan(tracked(a.root), terms)
    for p, n, line in hits:
        print(f"{p}:{n}: {line}")
    print(f"{a.root}: {'HITS' if hits else 'clean'} ({len(terms)} personal term(s) + built-ins)")
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    main()
