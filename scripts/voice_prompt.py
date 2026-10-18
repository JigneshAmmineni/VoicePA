"""Load system-prompt.md as the full system prompt (replaces the claude_code preset).

The file is edited as a document, so it carries HTML comments with provenance notes
for the editor. Those are stripped here; everything else is sent verbatim.

    from scripts.voice_prompt import load
    options = ClaudeAgentOptions(system_prompt=load())

If the file ever outgrows the Windows command-line limit (~32k chars), switch to
system_prompt={"type": "file", "path": str(PROMPT)} and strip comments on disk.
"""

import os
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
PROMPT = PROJECT / "system-prompt.md"
# Claude Code's auto-memory folder for this project: ~/.claude/projects/<project path with
# every non-alphanumeric character replaced by "-">/memory. system-prompt.md refers to it
# as {{MEMORY_DIR}} so the prompt is not tied to one machine or user name.
MEMORY_DIR = Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(PROJECT)) / "memory"
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def load(path=PROMPT):
    text = Path(path).read_text(encoding="utf-8")
    text = _COMMENT.sub("", text).replace("{{MEMORY_DIR}}", str(MEMORY_DIR) + os.sep)
    # collapse the blank runs the comments leave behind
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(load())
