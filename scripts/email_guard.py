"""PreToolUse hook: sending email is a human action, never the agent's.

Denies the gws CLI forms that send mail — +send, +reply, +reply-all, +forward, and the
raw API methods messages.send / drafts.send — in every permission mode, including
bypassPermissions (hooks run before the permission flow). Drafting is allowed: the
agent creates a Gmail draft and the user presses Send in Gmail themselves.

Scope is deliberately the smallest that closes the door: nothing else under gws, and
nothing outside Bash, is touched. It inspects the command string, so it cannot see a
send hidden inside another program; for a guarantee at the API level, remove the
gmail.send scope from the gws credential.

Wired up in .claude/settings.json. Reads the hook payload as JSON on stdin and writes
a decision as JSON on stdout (nothing written means "allow").
"""

import json
import re
import sys

SEND = re.compile(
    r"\bgws\s+gmail\s+(?:\+send|\+reply(?:-all)?|\+forward|(?:\S+[.\s]+)*(?:messages|drafts)[.\s]+send)\b",
    re.IGNORECASE,
)

REASON = (
    "Sending email is blocked by policy: the user sends mail themselves. "
    "Create a Gmail draft instead (the gws drafts create method; find its exact form with "
    "`gws schema`), then tell the user the draft is waiting in Gmail for them to review "
    "and press Send."
)


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    if data.get("hook_event_name") != "PreToolUse" or data.get("tool_name") != "Bash":
        return
    command = (data.get("tool_input") or {}).get("command", "")
    if not SEND.search(command):
        return
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": REASON,
            }
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
