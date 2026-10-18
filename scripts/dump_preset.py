"""Capture the claude_code preset system prompt, verbatim, to preset-dump.md.

The preset lives inside the Claude Code binary and can't be read as a file. The
documented way to see what Claude actually receives is OTEL_LOG_RAW_API_BODIES,
which makes Claude Code write every request body to a directory. So: run one
minimal query with the preset explicitly selected, then pull `system` out of the
logged request.

    uv run python scripts/dump_preset.py

Uses the claude login subscription: ANTHROPIC_API_KEY is removed from the
environment first, because it would take precedence.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

ROOT = Path(__file__).resolve().parent.parent
DUMP_DIR = ROOT / "logs" / "prompt-dump"
OUT = ROOT / "preset-dump.md"


def system_text(body):
    """`system` is a string, or a list of text blocks (with cache_control)."""
    system = body.get("system")
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n\n".join(b.get("text", "") for b in system if isinstance(b, dict))
    return None


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    os.environ.pop("ANTHROPIC_API_KEY", None)
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    for old in DUMP_DIR.iterdir():
        old.unlink()
    os.environ["OTEL_LOG_RAW_API_BODIES"] = f"file:{DUMP_DIR}"

    async for msg in query(
        prompt="Reply with the single word: ok",
        options=ClaudeAgentOptions(
            cwd=str(ROOT),
            system_prompt={"type": "preset", "preset": "claude_code"},
            max_turns=1,
            allowed_tools=[],
        ),
    ):
        if isinstance(msg, ResultMessage):
            print(f"query: {msg.subtype}, {msg.num_turns} turn(s), model_usage keys: {list((msg.model_usage or {}).keys())}")

    files = sorted(DUMP_DIR.glob("*"))
    print(f"logged {len(files)} request body file(s) in {DUMP_DIR}")
    if not files:
        sys.exit("no request bodies were written — OTEL_LOG_RAW_API_BODIES may not have reached the subprocess")

    for f in files:
        try:
            body = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        text = system_text(body)
        if text:
            OUT.write_text(text, encoding="utf-8")
            print(f"wrote {OUT.name}: {len(text):,} chars, {text.count(chr(10)) + 1:,} lines (from {f.name})")
            return
    sys.exit("found request bodies but none had a usable `system` field — inspect logs/prompt-dump/")


if __name__ == "__main__":
    asyncio.run(main())
