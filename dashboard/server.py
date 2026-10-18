"""VoicePA dashboard server.

Serves the dashboard UI, a small JSON API over the state/ files, and the long-lived
Claude Code session behind the chat panel (see agent.py).
- Every GET re-reads state from disk: refreshing the page always shows current state.
- Every mutation does a fresh read -> single-field change -> atomic write (temp file + os.replace),
  so it never clobbers edits made concurrently by Claude or other tools.
- Binds to localhost only. Exits silently if the port is already taken (another instance is serving).
"""

import asyncio
import dataclasses
import json
import os
import re
import socket
import sys
import tempfile
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

import time

import httpx
import numpy as np
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
sys.path.insert(0, str(ROOT))
from agent import Agent  # noqa: E402
from sanitize import sanitize  # noqa: E402

# Under pythonw (the launcher) there is no console: sys.stdout / sys.stderr are None, and
# uvicorn's log formatter calls sys.stdout.isatty() and dies before the port ever opens.
# Give both a file instead, which also means launcher-started servers leave a log.
if sys.stdout is None or sys.stderr is None:
    (PROJECT / "logs").mkdir(exist_ok=True)
    sys.stdout = sys.stderr = open(PROJECT / "logs" / "server.log", "a", encoding="utf-8", buffering=1)

# Auth: a key inherited from the shell would silently override the Claude Code sign-in,
# so it is dropped before .env loads. A key written in .env is deliberate and is kept.
os.environ.pop("ANTHROPIC_API_KEY", None)
load_dotenv(PROJECT / ".env")
# The claude.ai MCP connectors load whenever the session authenticates with claude.ai login;
# this PA uses the gws CLI instead, and their tool schemas cost tokens on every call.
os.environ.setdefault("ENABLE_CLAUDEAI_MCP_SERVERS", "false")

PORT = int(os.environ.get("DASH_PORT", "7789"))
STATE = Path(os.environ.get("DASH_STATE_DIR", PROJECT / "state"))

# voice providers — all optional; the UI disables what isn't configured
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")
DEEPGRAM_MODEL = os.environ.get("DEEPGRAM_MODEL", "nova-3")
CARTESIA_API_KEY = os.environ.get("CARTESIA_API_KEY", "")
CARTESIA_VOICE_ID = os.environ.get("CARTESIA_VOICE_ID", "")
CARTESIA_MODEL = os.environ.get("CARTESIA_MODEL", "sonic-3")
CARTESIA_SPEED = float(os.environ.get("CARTESIA_SPEED", "0.90"))  # 0.6–1.5; 1.0 = native pace
CARTESIA_VOLUME = float(os.environ.get("CARTESIA_VOLUME", "1.0"))  # 0.5–2.0
CARTESIA_EMOTION = os.environ.get("CARTESIA_EMOTION", "sarcastic")  # unset: the model reads the transcript's subtext


def _generation_config():
    cfg = {"speed": CARTESIA_SPEED, "volume": CARTESIA_VOLUME}
    if CARTESIA_EMOTION:
        cfg["emotion"] = CARTESIA_EMOTION
    return cfg

# hands-free endpointing, done on the page: after the wake word, recording stops once
# WAKE_SILENCE_MS pass with nothing above WAKE_SPEECH_RMS, or at WAKE_MAX_MS regardless
WAKE_SILENCE_MS = int(os.environ.get("WAKE_SILENCE_MS", "3000"))
WAKE_MAX_MS = int(os.environ.get("WAKE_MAX_MS", "15000"))
WAKE_SPEECH_RMS = float(os.environ.get("WAKE_SPEECH_RMS", "0.02"))
# follow-up window: after a spoken reply the page keeps the mic open this long, so the next
# sentence needs no wake word or hotkey. Each spoken turn earns a new window. 0 disables.
FOLLOWUP_MS = int(os.environ.get("FOLLOWUP_MS", "12000"))

# wake word: openWakeWord runs server-side; the browser streams 16 kHz mono int16 PCM
# over /ws/wake. A built-in model name (hey_jarvis, alexa, hey_mycroft, hey_rhasspy) or a
# path to an .onnx (relative paths resolve from the project root). Default: the community
# "computer" model from fwartner/home-assistant-wakewords-collection, see models/wake/README.md.
WAKE_MODEL = os.environ.get("WAKE_MODEL", "models/wake/computer_v1.onnx")
WAKE_THRESHOLD = float(os.environ.get("WAKE_THRESHOLD", "0.5"))
WAKE_VAD = float(os.environ.get("WAKE_VAD", "0"))  # Silero VAD gate on predictions; 0 = off
WAKE_COOLDOWN = 2.0  # seconds; one detection per utterance, not one per frame

# global hotkey (pynput syntax: <f8>, <ctrl>+<alt>+<space>, ...; empty disables). One press
# starts a voice turn in the dashboard tab, which records until the usual silence
# endpointing fires; a press while recording ends the turn early; a press while the
# assistant speaks or thinks is a barge-in. The key is not swallowed: the focused app
# sees it too, so pick one that app doesn't use.
HOTKEY = os.environ.get("HOTKEY", "<f8>").strip()
HOTKEY_OK, HOTKEY_ERROR = False, None


def _load_wake_model():
    """openwakeword 0.4.x API: explicit .onnx paths. A bare name resolves to the bundled model."""
    try:
        import openwakeword
        from openwakeword.model import Model
    except ImportError:
        return None, "openwakeword not installed"
    try:
        path = Path(WAKE_MODEL)
        if path.suffix and not path.is_absolute():
            path = PROJECT / path
        if not path.suffix:
            bundled = Path(openwakeword.__file__).parent / "resources" / "models"
            hits = sorted(bundled.glob(f"{WAKE_MODEL}*.onnx"))
            if not hits:
                return None, f"no bundled model named {WAKE_MODEL!r} in {bundled}"
            path = hits[0]
        return Model(wakeword_model_paths=[str(path)], vad_threshold=WAKE_VAD), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


_probe, WAKE_ERROR = _load_wake_model()
WAKE_OK = _probe is not None
del _probe

WRITE_LOCK = threading.Lock()
SERVER = None
START_TIME = None

GROUP_ORDER = ["morning", "daily", "night"]


def read_json(path, default):
    """Read a JSON state file fresh from disk. One retry in case we catch a mid-write."""
    for attempt in (0, 1):
        try:
            with open(path, encoding="utf-8-sig") as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except json.JSONDecodeError:
            if attempt == 0:
                threading.Event().wait(0.1)
            else:
                raise


def write_json(path, data):
    """Atomic write: temp file in the same directory, then os.replace."""
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


def today_str():
    return date.today().isoformat()


def mmddyyyy(iso):
    y, m, d = iso.split("-")
    return f"{m}-{d}-{y}"


def compute_streak(log, habit_name):
    """Consecutive days (ending today or yesterday) with a done/partial entry."""
    def hit(day):
        return any(
            e.get("habit") == habit_name and e.get("status") in ("done", "partial")
            for e in log.get(day.isoformat(), [])
        )

    day = date.today()
    if not hit(day):
        day = day - timedelta(days=1)  # today not logged yet doesn't break the streak
    streak = 0
    while hit(day):
        streak += 1
        day = day - timedelta(days=1)
    return streak


def build_state():
    today = today_str()

    dash = read_json(STATE / "dashboard.json", {})
    todayf = read_json(STATE / "today.json", {})
    tasks_all = read_json(STATE / "tasks.json", [])
    habits = read_json(STATE / "habits.json", {"habits": [], "log": {}})
    priorities = read_json(STATE / "priorities.json", {"priorities": []})
    journal = read_json(STATE / "journal.json", {"entries": []})

    # archived tasks can still be referenced by today.json (completed mid-day, then swept)
    archive = read_json(STATE / "tasks_archive.json", [])
    by_id = {t.get("id"): t for t in archive if isinstance(t, dict)}
    by_id.update({t.get("id"): t for t in tasks_all if isinstance(t, dict)})

    # tasks selected for today, joined with live status from tasks.json
    tasks = []
    for sel in todayf.get("tasks", []):
        full = by_id.get(sel.get("id"), {})
        tasks.append({
            "id": sel.get("id"),
            "title": full.get("title", sel.get("title", "")),
            "priority": (full.get("priority") or sel.get("priority") or "").upper(),
            "time_needed": full.get("time_needed") or sel.get("time_needed") or "",
            "due_date": full.get("due_date"),
            "status": full.get("status"),
            "done": full.get("status") == "done",
        })

    # Waiting tasks. A waiting task completed from the dashboard stays listed for the
    # rest of the day (struck through) instead of vanishing mid-click; wrap-up flushes it.
    waiting = []
    for t in tasks_all:
        if not isinstance(t, dict):
            continue
        notes = (t.get("notes") or "").lstrip()
        status = t.get("status")
        done_today = status == "done" and t.get("completed_at") == today and notes.startswith("WAITING ON:")
        if status != "waiting" and not done_today:
            continue
        m = re.match(r"WAITING ON:\s*([^.\n]+)", notes)
        waiting.append({
            "id": t.get("id"),
            "title": t.get("title", ""),
            "waiting_on": ("WAITING ON: " + m.group(1).strip()) if m else "WAITING ON: (see notes)",
            "due_date": t.get("due_date"),
            "done": done_today,
        })

    # habits with streaks + today's log status
    log = habits.get("log", {})
    today_log = {e.get("habit"): e.get("status") for e in log.get(today, [])}
    habit_rows = []
    for h in habits.get("habits", []):
        habit_rows.append({
            "name": h.get("name"),
            "group": h.get("group"),
            "streak": compute_streak(log, h.get("name")),
            "today": today_log.get(h.get("name")),
        })
    habit_rows.sort(key=lambda r: GROUP_ORDER.index(r["group"]) if r["group"] in GROUP_ORDER else len(GROUP_ORDER))

    return {
        "date": today,
        "date_display": mmddyyyy(today),
        "weekday": date.today().strftime("%A").upper(),
        "focus": dash.get("focus") or "",
        "compyutah_line": dash.get("compyutah_line") or "",
        "dash_stale": dash.get("date") != today,
        "plan_stale": todayf.get("date") != today,
        "plan_date": todayf.get("date"),
        "agenda": dash.get("agenda") or [],
        "emails": dash.get("emails") or [],
        "email_footnotes": dash.get("email_footnotes") or [],
        "tasks": tasks,
        "waiting": waiting,
        "habits": habit_rows,
        "priorities": [p for p in priorities.get("priorities", []) if not p.get("resolved_at")],
        "journal_exists": any(e.get("date") == today for e in journal.get("entries", [])),
    }


# ---------------- mutations ----------------

def mutate_task(task_id, done, prev=None):
    """prev = the status the UI rendered, so un-checking restores waiting/in_progress
    rather than flattening everything to todo."""
    with WRITE_LOCK:
        path = STATE / "tasks.json"
        tasks = read_json(path, [])
        task = next((t for t in tasks if isinstance(t, dict) and t.get("id") == task_id), None)
        if task is None:
            archive = read_json(STATE / "tasks_archive.json", [])
            archived = next((t for t in archive if isinstance(t, dict) and t.get("id") == task_id), None)
            if archived is not None:
                if done and archived.get("status") == "done":
                    return True, None  # already done and archived — idempotent
                return False, f"{task_id} is archived — ask Claude to restore it"
            return False, f"task {task_id} not found"
        if done:
            task["status"] = "done"
            task["completed_at"] = today_str()
        else:
            task["status"] = prev if prev in ("todo", "waiting", "in_progress") else "todo"
            task.pop("completed_at", None)
        write_json(path, tasks)
    return True, None


def mutate_habit(name, mark_done):
    with WRITE_LOCK:
        path = STATE / "habits.json"
        habits = read_json(path, None)
        if habits is None:
            return False, "habits.json missing"
        if not any(h.get("name") == name for h in habits.get("habits", [])):
            return False, f"habit {name!r} not in active list"
        day = today_str()
        entries = habits.setdefault("log", {}).setdefault(day, [])
        entries[:] = [e for e in entries if e.get("habit") != name]
        if mark_done:
            entries.append({"habit": name, "status": "done", "progress": None})
        if not entries:
            del habits["log"][day]
        # keep log keys newest-first so today's entry is at the top of the file
        habits["log"] = dict(sorted(habits["log"].items(), reverse=True))
        write_json(path, habits)
    return True, None


def mutate_journal(note):
    note = (note or "").rstrip()
    if not note.strip():
        return False, "empty note"
    with WRITE_LOCK:
        path = STATE / "journal.json"
        journal = read_json(path, {"entries": []})
        day = today_str()
        entry = next((e for e in journal.get("entries", []) if e.get("date") == day), None)
        if entry:
            entry["note"] = entry.get("note", "").rstrip() + "\n" + note
        else:
            # newest first — appending buries today's entry at the bottom of a long file
            journal.setdefault("entries", []).insert(0, {"date": day, "note": note})
        write_json(path, journal)
    return True, None


# ---------------- http ----------------

agent = Agent()


def _start_hotkey(loop):
    """Returns (listener, error). pynput runs the hook in its own thread; the only thing
    it touches on the event loop is agent.emit, via call_soon_threadsafe, and the event
    is not recorded so a reconnecting page never replays a key press."""
    if not HOTKEY:
        return None, "disabled"
    try:
        from pynput import keyboard
    except ImportError:
        return None, "pynput not installed"

    def fire():
        loop.call_soon_threadsafe(agent.emit, {"type": "hotkey", "ts": time.time()}, False)

    # Listener + HotKey rather than GlobalHotKeys: the latter ignores injected key events,
    # which makes it untestable with a synthetic press (and would ignore macro tools too).
    # HotKey.parse turns every non-generic key into a bare key code (<ctrl_r> -> vk 163),
    # while the listener delivers Key.ctrl_r, an enum whose .value has the same vk but an
    # extra win32 "extended key" flag, so the two never compare equal. listener.canonical()
    # can't bridge it either: it folds ctrl_r into the generic ctrl. So a delivered Key is
    # matched by vk number against the hotkey's own keys and the parsed object is handed
    # to HotKey; anything else is normalised (combos like <ctrl>+e need that: the raw key
    # arrives as the control character). This is what lets a single side-specific
    # modifier such as <ctrl_r> work.
    try:
        keys = set(keyboard.HotKey.parse(HOTKEY))
        hotkey = keyboard.HotKey(keys, fire)
        by_vk = {k.vk: k for k in keys if isinstance(k, keyboard.KeyCode) and k.char is None}

        def pick(k):
            v = getattr(k, "value", None)   # Key enum -> its KeyCode; plain KeyCode -> None
            return by_vk[v.vk] if v is not None and v.vk in by_vk else listener.canonical(k)

        listener = keyboard.Listener(on_press=lambda k: hotkey.press(pick(k)),
                                     on_release=lambda k: hotkey.release(pick(k)))
        listener.start()
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    return listener, None


@asynccontextmanager
async def lifespan(app):
    global HOTKEY_OK, HOTKEY_ERROR
    # start in the background so the page loads while Claude Code is still spawning
    asyncio.create_task(agent.start())
    hk, HOTKEY_ERROR = _start_hotkey(asyncio.get_running_loop())
    HOTKEY_OK = hk is not None
    if HOTKEY and HOTKEY_ERROR:
        print(f"[dash] hotkey {HOTKEY!r} unavailable: {HOTKEY_ERROR}", file=sys.stderr)
    yield
    if hk is not None:
        hk.stop()
    await agent.stop()


app = FastAPI(lifespan=lifespan)
(ROOT / "static").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")  # porcupine model, etc.


def _jsonable(o):
    return dataclasses.asdict(o) if dataclasses.is_dataclass(o) else str(o)


def _sse(ev):
    return f"data: {json.dumps(ev, ensure_ascii=False, default=_jsonable)}\n\n"


async def _body(request):
    try:
        return await request.json()
    except (ValueError, json.JSONDecodeError):
        return None


def _result(ok, err=None):
    return JSONResponse({"ok": ok, "error": err}, status_code=200 if ok else 400)


@app.get("/", response_class=HTMLResponse)
async def index():
    return (ROOT / "index.html").read_text(encoding="utf-8")


@app.get("/api/ping")
async def ping():
    # "app" is how stop-dashboard.bat tells this server apart from a stranger on the port
    return {"ok": True, "app": "voicepa", "started": START_TIME}


@app.get("/api/state")
async def api_state():
    try:
        return build_state()
    except Exception as e:  # surface state-file problems to the UI
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/task")
async def api_task(request: Request):
    p = await _body(request)
    if p is None:
        return JSONResponse({"error": "bad json"}, status_code=400)
    ok, err = await asyncio.to_thread(mutate_task, p.get("id"), bool(p.get("done")), p.get("prev"))
    return _result(ok, err)


@app.post("/api/habit")
async def api_habit(request: Request):
    p = await _body(request)
    if p is None:
        return JSONResponse({"error": "bad json"}, status_code=400)
    ok, err = await asyncio.to_thread(mutate_habit, p.get("name"), bool(p.get("done")))
    return _result(ok, err)


@app.post("/api/journal")
async def api_journal(request: Request):
    p = await _body(request)
    if p is None:
        return JSONResponse({"error": "bad json"}, status_code=400)
    ok, err = await asyncio.to_thread(mutate_journal, p.get("note"))
    return _result(ok, err)


@app.post("/api/shutdown")
async def api_shutdown():
    # lets `planner.py restart` pick up code changes — without this, a new instance
    # silently exits because the port is taken and stale code keeps serving
    if SERVER is not None:
        SERVER.should_exit = True
    return {"ok": True}


# ---- agent ----

@app.get("/api/agent")
async def api_agent():
    return agent.snapshot()


@app.get("/api/events")
async def api_events(request: Request):
    q = agent.subscribe()

    async def gen():
        try:
            for ev in agent.replay():
                yield _sse(ev)
            yield _sse({"type": "replay_end"})   # the UI speaks only what arrives after this
            while not await request.is_disconnected():
                try:
                    yield _sse(await asyncio.wait_for(q.get(), 15))
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            agent.unsubscribe(q)

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.post("/api/chat")
async def api_chat(request: Request):
    p = await _body(request)
    text = (p or {}).get("text", "").strip() if p else ""
    if not text:
        return JSONResponse({"error": "empty message"}, status_code=400)
    try:
        agent.send(text, origin=(p or {}).get("origin"))
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=409 if agent.busy else 503)
    return {"ok": True}


@app.post("/api/permission")
async def api_permission(request: Request):
    p = await _body(request)
    if not p or not p.get("id") or p.get("behavior") not in ("allow", "deny"):
        return JSONResponse({"error": "need id and behavior allow|deny"}, status_code=400)
    if not agent.resolve(p["id"], p):
        return JSONResponse({"error": "no such pending request"}, status_code=404)
    return {"ok": True}


@app.post("/api/interrupt")
async def api_interrupt():
    return {"ok": True, "interrupted": await agent.interrupt()}


@app.post("/api/session")
async def api_session(request: Request):
    p = await _body(request) or {}
    action = p.get("action")
    if action == "stop":
        await agent.stop()
    elif action == "start":
        asyncio.create_task(agent.start())
    elif action == "new":
        await agent.stop()
        asyncio.create_task(agent.start(fresh=True))
    else:
        return JSONResponse({"error": "action must be start|stop|new"}, status_code=400)
    return {"ok": True}


@app.post("/api/model")
async def api_model(request: Request):
    p = await _body(request) or {}
    if agent.client is None:
        return JSONResponse({"error": "agent is not running"}, status_code=503)
    await agent.client.set_model(p.get("model") or None)
    return {"ok": True}


@app.post("/api/permission_mode")
async def api_permission_mode(request: Request):
    p = await _body(request) or {}
    if agent.client is None:
        return JSONResponse({"error": "agent is not running"}, status_code=503)
    await agent.client.set_permission_mode(p.get("mode"))
    return {"ok": True}


# ---- voice ----

@app.get("/api/config")
async def api_config():
    """What the browser needs to decide which voice controls to enable."""
    return {
        "stt": bool(DEEPGRAM_API_KEY),
        "tts": bool(CARTESIA_API_KEY and CARTESIA_VOICE_ID),
        "wake": WAKE_OK,
        "wake_word": re.sub(r"_v\d+$", "", os.path.splitext(os.path.basename(WAKE_MODEL))[0]).replace("_", " "),
        "wake_error": WAKE_ERROR,
        "silence_ms": WAKE_SILENCE_MS,
        "max_utterance_ms": WAKE_MAX_MS,
        "speech_rms": WAKE_SPEECH_RMS,
        "followup_ms": FOLLOWUP_MS,
        "hotkey": re.sub(r"[<>]", "", HOTKEY).upper() if HOTKEY_OK else None,   # "<f8>" -> "F8" for the tooltip
        "hotkey_error": HOTKEY_ERROR if HOTKEY else None,
    }


@app.websocket("/ws/wake")
async def ws_wake(ws: WebSocket):
    """Binary frames of 16 kHz mono int16 PCM in; {"wake": name, "score": x} out on detection.
    One detector per connection: the model keeps a rolling audio buffer."""
    await ws.accept()
    model, err = _load_wake_model()
    if model is None:
        await ws.send_json({"error": err})
        await ws.close()
        return
    await ws.send_json({"ready": True, "wake_word": WAKE_MODEL, "threshold": WAKE_THRESHOLD})
    last = 0.0
    try:
        while True:
            frame = np.frombuffer(await ws.receive_bytes(), dtype=np.int16)
            scores = await asyncio.to_thread(model.predict, frame)
            name, score = max(scores.items(), key=lambda kv: kv[1]) if scores else (None, 0.0)
            now = time.time()
            if name and score >= WAKE_THRESHOLD and now - last > WAKE_COOLDOWN:
                last = now
                await ws.send_json({"wake": name, "score": round(float(score), 3)})
    except WebSocketDisconnect:
        pass


@app.post("/api/transcribe")
async def api_transcribe(request: Request):
    """Raw audio bytes in, transcript out. Content-Type is passed through to Deepgram."""
    if not DEEPGRAM_API_KEY:
        return JSONResponse({"error": "DEEPGRAM_API_KEY not set"}, status_code=503)
    audio = await request.body()
    if not audio:
        return JSONResponse({"error": "empty audio"}, status_code=400)
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(
            "https://api.deepgram.com/v1/listen",
            params={"model": DEEPGRAM_MODEL, "smart_format": "true", "language": "en"},
            headers={"Authorization": f"Token {DEEPGRAM_API_KEY}",
                     "Content-Type": request.headers.get("content-type", "audio/webm")},
            content=audio,
        )
    if r.status_code != 200:
        return JSONResponse({"error": f"deepgram {r.status_code}: {r.text[:300]}"}, status_code=502)
    try:
        text = r.json()["results"]["channels"][0]["alternatives"][0]["transcript"]
    except (KeyError, IndexError, ValueError):
        return JSONResponse({"error": "deepgram: no transcript in response"}, status_code=502)
    return {"text": text}


@app.post("/api/speak")
async def api_speak(request: Request):
    """Text in, mp3 bytes out. Sanitized first so markdown never gets read aloud."""
    if not (CARTESIA_API_KEY and CARTESIA_VOICE_ID):
        return JSONResponse({"error": "CARTESIA_API_KEY / CARTESIA_VOICE_ID not set"}, status_code=503)
    p = await _body(request) or {}
    text = sanitize(p.get("text", ""))
    if not text:
        return JSONResponse({"error": "nothing to say"}, status_code=400)
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.post(
            "https://api.cartesia.ai/tts/bytes",
            headers={"Authorization": f"Bearer {CARTESIA_API_KEY}",
                     "Cartesia-Version": "2026-08-14", "Content-Type": "application/json"},
            json={
                "model_id": CARTESIA_MODEL,
                "transcript": text,
                "voice": {"id": CARTESIA_VOICE_ID},
                "output_format": {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000},
                "generation_config": _generation_config(),
            },
        )
    if r.status_code != 200:
        return JSONResponse({"error": f"cartesia {r.status_code}: {r.text[:300]}"}, status_code=502)
    return Response(content=r.content, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/context")
async def api_context():
    if agent.client is None:
        return JSONResponse({"error": "agent is not running"}, status_code=503)
    usage = await agent.client.get_context_usage()
    return json.loads(json.dumps(usage, default=_jsonable))


def main():
    global SERVER, START_TIME
    # port taken: another instance is already serving — nothing to do
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", PORT))
        except OSError:
            sys.exit(0)
    # sys.stderr is None under pythonw — logging must never break a response
    quiet = sys.stderr is None
    config = uvicorn.Config(
        app, host="127.0.0.1", port=PORT,
        log_level="critical" if quiet else "info", access_log=not quiet,
    )
    SERVER = uvicorn.Server(config)
    START_TIME = datetime.now().isoformat(timespec="seconds")
    if not quiet:
        print(f"[dash] serving http://127.0.0.1:{PORT}  state={STATE}")
    SERVER.run()


if __name__ == "__main__":
    main()
