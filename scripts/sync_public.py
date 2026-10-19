"""Ship main's committed tree to the public orphan branch as one snapshot commit.

The public branch has no history in common with main and must never get any: no merge,
no rebase, no moving its pointer. So shipping means copying main's files into the public
worktree, leaving out what is private, checking that nothing personal slipped through,
and committing the result as a single snapshot.

  python scripts/sync_public.py             # sync, scan, commit on public
  python scripts/sync_public.py --dry-run   # show what would change, write nothing

Never copied: state/*.json (public keeps its empty templates), preset-dump.md, anything
gitignored. Public's own, never removed: README.md, LICENSE. Refuses to run while the
public worktree has uncommitted changes, and refuses to commit when scan_public.py finds
a hit or a scrub invariant is missing.

Files are compared by blob id, not by bytes on disk, so line-ending conversion in the
working tree never shows up as a change, and they are copied with `git checkout main --
<path>` run inside the public worktree, which moves content only.
"""

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_public import load_terms, scan  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
SOURCE, BRANCH = "main", "public"
NEVER_COPIED = ["state/*.json", "preset-dump.md"]
PUBLIC_ONLY = ["README.md", "LICENSE", "state/*.json"]


def git(*args, cwd=PROJECT):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, check=True).stdout


def text(*args, cwd=PROJECT):
    return git(*args, cwd=cwd).decode("utf-8").strip()


def matches(path, patterns):
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def tree_of(ref):
    """{path: blob id} for a ref."""
    out = {}
    for line in text("ls-tree", "-r", ref).splitlines():
        meta, path = line.split("\t", 1)
        out[path] = meta.split()[2]
    return out


def public_worktree():
    cur = None
    for line in text("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            cur = Path(line[len("worktree "):])
        elif line == f"branch refs/heads/{BRANCH}":
            return cur
    sys.exit(f"no worktree has {BRANCH!r} checked out. Create one: git worktree add ../VoicePA-public {BRANCH}")


def invariants(tree):
    """The scrub that must hold on the public tree, checked rather than re-applied."""
    out = []
    prompt = tree.get("system-prompt.md", b"").decode("utf-8", "replace")
    if "{{MEMORY_DIR}}" not in prompt:
        out.append("system-prompt.md: the memory path must be the {{MEMORY_DIR}} placeholder")
    server = tree.get("dashboard/server.py", b"").decode("utf-8", "replace")
    if not 0 <= server.find('os.environ.pop("ANTHROPIC_API_KEY"') < server.find("load_dotenv("):
        out.append("dashboard/server.py: ANTHROPIC_API_KEY must be popped before .env loads")
    for p in ("README.md", "LICENSE"):
        if p not in tree:
            out.append(f"{p}: missing from {BRANCH}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="report only, write and commit nothing")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    wt = public_worktree()
    if text("status", "--porcelain", cwd=wt):
        sys.exit(f"{wt} has uncommitted changes. Commit or discard them first.")
    sha = text("rev-parse", SOURCE)
    source = {p: b for p, b in tree_of(SOURCE).items() if not matches(p, NEVER_COPIED)}
    public = tree_of(BRANCH)

    updates = [p for p in source if public.get(p) != source[p]]
    removals = [p for p in public if p not in source and not matches(p, PUBLIC_ONLY) and not matches(p, NEVER_COPIED)]

    # the tree public would have afterwards, read from blobs so line endings play no part
    tree = {p: git("show", f"{SOURCE}:{p}") for p in source}
    tree.update({p: git("show", f"{BRANCH}:{p}") for p in public if p not in source and p not in removals})
    problems = invariants(tree)
    problems += [f"{p}:{n}: {line}" for p, n, line in scan(tree.items(), load_terms(PROJECT / "private_terms.txt"))]

    print(f"{SOURCE} @ {sha[:7]}  ->  {BRANCH} in {wt}")
    for p in updates:
        print(f"  update  {p}")
    for p in removals:
        print(f"  remove  {p}")
    if not updates and not removals:
        print("nothing to sync.")
        return
    if problems:
        print("\nnot committing. Fix on main first:")
        for x in problems:
            print("  " + x)
        sys.exit(1)
    if a.dry_run:
        print(f"\ndry run: {len(updates)} update(s), {len(removals)} removal(s), scan clean. Nothing written.")
        return

    if updates:
        git("checkout", SOURCE, "--", *updates, cwd=wt)   # content only; no history moves
    if removals:
        git("rm", "-q", "--", *removals, cwd=wt)
    git("commit", "-q", "-m",
        f"Sync from {SOURCE} {sha[:7]}\n\nSnapshot of {SOURCE}'s tree: {len(updates)} file(s) updated, "
        f"{len(removals)} removed. State files and private files left out.", cwd=wt)
    print(f"\ncommitted on {BRANCH}: {text('log', '--oneline', '-1', cwd=wt)}")
    print(f'push with:  git -C "{wt}" push')   # the branch's upstream, set when it was first published


if __name__ == "__main__":
    main()
