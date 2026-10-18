"""The long-lived Claude Code session behind the dashboard.

One ClaudeSDKClient, owned by the FastAPI lifespan, in streaming input mode.
Every SDK message becomes a small JSON event fanned out to SSE subscribers;
permission requests and AskUserQuestion calls become events the UI answers over
HTTP, resolving a Future the SDK callback is awaiting.

Rules this file exists to enforce (see handoff-VoicePA.md):
- one query() per receive_response() loop, and the loop is never broken early
- interrupt() does not clear the buffer: the in-flight loop drains it
- can_use_tool needs a no-op PreToolUse hook registered or it never fires
- one session per day: resume today's, otherwise start fresh
"""

import asyncio
import json
import os
import sys
import time
import uuid
from collections import deque
from datetime import date
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from scripts.voice_prompt import load as load_system_prompt  # noqa: E402

SESSION_FILE = PROJECT / "state" / ".session_id"
REPLAY_LIMIT = 500
INTERRUPT_DRAIN_TIMEOUT = 30


async def _keepalive_hook(input_data, tool_use_id, context):
    """Documented workaround: a PreToolUse hook keeps the stream open so can_use_tool fires."""
    return {"continue_": True}


def _event(type_, **fields):
    # first parameter deliberately not named `kind`: permission events carry a `kind` field
    return {"type": type_, "ts": time.time(), **fields}


def to_events(msg):
    """Flatten one SDK message into zero or more UI events."""
    if isinstance(msg, AssistantMessage):
        out = []
        for b in msg.content:
            if isinstance(b, TextBlock):
                out.append(_event("assistant_text", text=b.text))
            elif isinstance(b, ToolUseBlock):
                out.append(_event("tool_use", id=b.id, name=b.name, input=b.input))
            elif isinstance(b, ThinkingBlock):
                out.append(_event("thinking", text=b.thinking))
        return out
    if isinstance(msg, UserMessage):
        # tool results arrive as user-role messages; a plain string is our own prompt echoed back
        if not isinstance(msg.content, list):
            return []
        return [
            _event("tool_result", tool_use_id=b.tool_use_id, content=b.content, is_error=bool(b.is_error))
            for b in msg.content
            if isinstance(b, ToolResultBlock)
        ]
    if isinstance(msg, SystemMessage):
        if msg.subtype == "init":
            d = msg.data or {}
            return [_event("init", session_id=d.get("session_id"), model=d.get("model"),
                           permission_mode=d.get("permissionMode"), tools=d.get("tools", []),
                           mcp_servers=d.get("mcp_servers", []))]
        return [_event("system", subtype=msg.subtype)]
    if isinstance(msg, ResultMessage):
        return [_event(
            "result",
            subtype=msg.subtype, result=msg.result, session_id=msg.session_id,
            is_error=msg.is_error, terminal_reason=msg.terminal_reason, stop_reason=msg.stop_reason,
            num_turns=msg.num_turns, duration_ms=msg.duration_ms, total_cost_usd=msg.total_cost_usd,
            permission_denials=msg.permission_denials, errors=msg.errors,
            api_error_status=msg.api_error_status,
            usage=msg.usage,   # token counts incl. cache reads — the only way to see whether caching lands
        )]
    return []


class Agent:
    def __init__(self):
        self.client = None
        self.subscribers = set()
        self.history = deque(maxlen=REPLAY_LIMIT)
        self.pending = {}        # request id -> {"future", "suggestions"}
        self.turn = None         # the in-flight turn's task
        self.session_id = None
        self.status = "stopped"  # stopped | starting | idle | thinking | error
        self.error = None

    # ---------------- lifecycle ----------------

    def _todays_session(self):
        try:
            d = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        return d.get("session_id") if d.get("date") == date.today().isoformat() else None

    def _remember_session(self, sid):
        self.session_id = sid
        SESSION_FILE.write_text(
            json.dumps({"session_id": sid, "date": date.today().isoformat()}), encoding="utf-8"
        )

    def _options(self, resume):
        return ClaudeAgentOptions(
            cwd=str(PROJECT),
            model=os.environ.get("AGENT_MODEL", "claude-sonnet-5-5"),
            # no MCP at all: the PA works through the gws CLI and scripts/state.py. Externally
            # configured servers (user-level playwright, Notion, ...) cost tokens on every call
            # and connect asynchronously, which breaks the cached prompt prefix between turns.
            mcp_servers={},
            strict_mcp_config=True,
            system_prompt=load_system_prompt(),
            permission_mode="auto",
            can_use_tool=self._can_use_tool,
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[_keepalive_hook])]},
            resume=resume,
        )

    async def start(self, fresh=False):
        if self.client is not None:
            return
        if fresh:
            SESSION_FILE.unlink(missing_ok=True)
            self.history.clear()
        self.status, self.error = "starting", None
        self.emit(_event("status", status="starting"))

        resume = self._todays_session()
        for attempt in ("resume", "fresh"):
            try:
                client = ClaudeSDKClient(options=self._options(resume))
                await client.connect()
                break
            except Exception as e:
                if attempt == "resume" and resume:
                    SESSION_FILE.unlink(missing_ok=True)   # stale id: fall back to a fresh session
                    resume = None
                    continue
                self.status, self.error = "error", f"{type(e).__name__}: {e}"
                self.emit(_event("status", status="error", error=self.error))
                return
        self.client = client
        self.session_id = resume
        self.status = "idle"
        # model rides on the idle event so the footer is right before any turn's init arrives
        self.emit(_event("status", status="idle", session_id=self.session_id, resumed=bool(resume),
                         model=os.environ.get("AGENT_MODEL", "claude-sonnet-5-5")))

    async def stop(self):
        self._cancel_pending("session stopped")
        if self.busy:
            try:
                await self.client.interrupt()
                await asyncio.wait_for(asyncio.shield(self.turn), INTERRUPT_DRAIN_TIMEOUT)
            except Exception:
                pass
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass
        self.client = None
        self.status = "stopped"
        self.emit(_event("status", status="stopped"))

    # ---------------- turns ----------------

    @property
    def busy(self):
        return self.turn is not None and not self.turn.done()

    def send(self, text, origin=None):
        """origin = the browser tab's id. It rides on the user and result events so only
        the tab that asked speaks the answer, however many tabs are open."""
        if self.client is None:
            raise RuntimeError("agent is not running")
        if self.busy:
            raise RuntimeError("a turn is already in flight")
        self.turn = asyncio.create_task(self._run_turn(text, origin))

    async def _run_turn(self, text, origin):
        self.status = "thinking"
        self.emit(_event("user", text=text, origin=origin))
        self.emit(_event("status", status="thinking"))
        try:
            await self.client.query(text)
            async for msg in self.client.receive_response():   # ends at the ResultMessage; never break
                for ev in to_events(msg):
                    if ev["type"] == "result":
                        ev["origin"] = origin
                    self.emit(ev)
                if isinstance(msg, ResultMessage) and msg.session_id:
                    self._remember_session(msg.session_id)
        except Exception as e:
            self.emit(_event("error", error=f"{type(e).__name__}: {e}"))
        finally:
            self._cancel_pending("turn ended")
            self.status = "idle"
            self.emit(_event("status", status="idle"))

    async def interrupt(self):
        """Stop the in-flight turn. The running loop drains the aborted messages itself."""
        if not self.busy:
            return False
        self._cancel_pending("interrupted")
        await self.client.interrupt()
        try:
            await asyncio.wait_for(asyncio.shield(self.turn), INTERRUPT_DRAIN_TIMEOUT)
        except asyncio.TimeoutError:
            self.emit(_event("error", error="interrupt sent but the turn did not drain in time"))
        return True

    # ---------------- permissions ----------------

    async def _can_use_tool(self, tool_name, input_data, context):
        rid = uuid.uuid4().hex[:12]
        fut = asyncio.get_running_loop().create_future()
        suggestions = list(context.suggestions or [])
        self.pending[rid] = {"future": fut, "suggestions": suggestions}
        self.emit(_event(
            "permission_request",
            id=rid,
            kind="question" if tool_name == "AskUserQuestion" else "permission",
            tool=tool_name, input=input_data,
            title=context.title, description=context.description,
            decision_reason=context.decision_reason, blocked_path=context.blocked_path,
            can_remember=any(getattr(s, "destination", None) == "localSettings" for s in suggestions),
        ))
        try:
            d = await fut
        finally:
            self.pending.pop(rid, None)
        self.emit(_event("permission_resolved", id=rid, behavior=d.get("behavior")))

        if d.get("behavior") == "allow":
            remember = [s for s in suggestions if getattr(s, "destination", None) == "localSettings"]
            return PermissionResultAllow(
                updated_input=d.get("updated_input") or input_data,
                updated_permissions=remember if d.get("remember") else None,
            )
        return PermissionResultDeny(message=d.get("message") or "User declined")

    def resolve(self, rid, decision):
        rec = self.pending.get(rid)
        if rec is None or rec["future"].done():
            return False
        rec["future"].set_result(decision)
        return True

    def _cancel_pending(self, why):
        for rec in list(self.pending.values()):
            if not rec["future"].done():
                rec["future"].set_result({"behavior": "deny", "message": why})

    # ---------------- fan-out ----------------

    def subscribe(self):
        q = asyncio.Queue()
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q):
        self.subscribers.discard(q)

    def emit(self, ev, record=True):
        """record=False for ephemeral signals (a hotkey press) that must not replay to a
        reconnecting page."""
        if record:
            self.history.append(ev)
        for q in list(self.subscribers):
            q.put_nowait(ev)

    def replay(self):
        """History for a fresh subscriber. Unresolved permission cards survive a page reload
        because their request event is in here with no matching permission_resolved."""
        return list(self.history)

    def snapshot(self):
        return {
            "status": self.status, "error": self.error, "busy": self.busy,
            "session_id": self.session_id or self._todays_session(),
            "pending": list(self.pending),
        }
