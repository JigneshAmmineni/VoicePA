# VoicePA

A personal assistant you talk to. It runs a long-lived Claude Code session on your own machine, keeps your tasks, habits, priorities and lists in plain JSON files, reads your Gmail and Calendar through Google's `gws` CLI, and answers out loud. You start a turn by saying "computer", by pressing a global hotkey from anywhere on your computer, or by clicking a button on the dashboard. The reply comes back spoken, in a sentence or two.

It is built on the Claude Agent SDK. The agent's rules live in `CLAUDE.md` and `system-prompt.md`, the planning routines are three Claude Code skills, and a small FastAPI server with a single-page dashboard ties it together. Nothing leaves your machine except the model calls, speech to text and text to speech.

## What's in the box

| Path | What it is |
|---|---|
| `dashboard/server.py` | FastAPI server. Owns the Claude session, serves the dashboard, does speech to text, text to speech, wake word detection and the global hotkey. |
| `dashboard/agent.py` | The Claude Agent SDK session. One per day, resumed across restarts. |
| `dashboard/index.html` | The dashboard and chat panel. |
| `dashboard/start-dashboard.bat`, `stop-dashboard.bat` | Double-click to start or stop. |
| `state/` | Your data. Tasks, habits, priorities, journal, ideas, projects, research, shopping, watchlist. Ships empty. |
| `scripts/state.py` | The only way the agent writes state files. Ids, duplicate checks, atomic writes. |
| `scripts/email_guard.py`, `stale_guard.py` | Hooks. The first makes sending email impossible, the second blocks edits to a state file that was not freshly read. |
| `scripts/purge_sessions.py` | Deletes session transcripts idle for 30 days or more. Run it when you want. |
| `.claude/` | Permissions, hooks and the `daily-planner`, `weekly-review` and `wrap-up` skills. |
| `CLAUDE.md` | How the state files work and how the assistant should behave with them. |
| `system-prompt.md` | The full system prompt, including the personality. Edit freely. |
| `models/wake/` | The "computer" wake word models. |

## How a turn works

1. You say "computer", press the hotkey, or click TALK.
2. The browser records until you have been quiet for three seconds.
3. The audio goes to Deepgram and comes back as text.
4. The text goes to the Claude session, which reads and writes your state files and your Google data as needed. Tool calls show up as a collapsible card in the chat panel.
5. The final line is sent to Cartesia and played back.
6. The microphone stays open for twelve more seconds, so you can keep talking without the wake word.

## Requirements

- Windows. The launchers are batch files and the hooks in `.claude/settings.json` are PowerShell. The server itself is plain Python, so porting means replacing those two things.
- Python 3.13 or newer and [uv](https://docs.astral.sh/uv/).
- [Claude Code](https://claude.com/claude-code) installed, plus either a Claude subscription or an Anthropic API key.
- Node.js, for the `gws` CLI.
- A [Deepgram](https://deepgram.com) API key for speech to text.
- A [Cartesia](https://cartesia.ai) API key and a voice id for text to speech.
- A microphone. Chrome or Edge work; the page needs `getUserMedia` and an `AudioWorklet`.

## Setup

### 1. Install

```
git clone <this repo> VoicePA
cd VoicePA
uv sync
```

### 2. Keys

```
copy .env.example .env
```

Fill in `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY` and `CARTESIA_VOICE_ID`. The voice id comes from Cartesia's voice library; any voice works. Everything else in the file has a default and is commented out. The real `.env` is gitignored and must stay that way.

### 3. Claude

Pick one.

**Subscription.** Install Claude Code, run `claude` once in any folder and sign in. The server uses the same sign-in. Leave `ANTHROPIC_API_KEY` out of `.env`. This is for your own use on your own machine with your own subscription.

**API key.** Put `ANTHROPIC_API_KEY=...` in `.env`. You are billed per token. The turn cards in the chat panel show the running estimate. A key that is merely present in your shell environment is ignored, which is deliberate, so it has to be in the file.

The model defaults to Sonnet. Change `AGENT_MODEL` in `.env` to use another one.

### 4. Google Workspace

The assistant reads your inbox and calendar, drafts replies, and can touch Docs, Drive and Sheets, all through the [`gws` CLI](https://github.com/googleworkspace/cli). You need a Google Cloud OAuth client of your own, then a one-time sign-in.

Install the CLI:

```
npm install -g @googleworkspace/cli
```

Create the OAuth client. The easy way needs the `gcloud` CLI installed and signed in:

```
gws auth setup
```

That creates a Google Cloud project, enables the APIs, creates a desktop OAuth client and saves it where `gws` expects it. If you would rather do it by hand, in the Google Cloud console: create a project, enable the Gmail, Calendar, Docs, Drive and Sheets APIs, configure the OAuth consent screen as an external app in testing mode with your own address as a test user, create an OAuth client id of type Desktop app, download the JSON and save it as `~/.config/gws/client_secret.json`.

Sign in, asking only for the services this assistant uses:

```
gws auth login -s gmail,calendar,docs,drive,sheets
```

These are the scopes it needs. Nothing else is used.

| Service | Scope | What the assistant does with it |
|---|---|---|
| Gmail | `gmail.modify` | Reads the inbox for the daily plan, creates drafts for you to send. Sending from the assistant is blocked by a hook regardless of scope. `gmail.readonly` plus `gmail.compose` is a narrower pair that also works. |
| Calendar | `calendar` | Reads the day's agenda, creates events for tasks you schedule. `calendar.events` is enough. |
| Docs | `documents` | Reads and appends to documents when asked. |
| Drive | `drive` | Browses and uploads when asked. |
| Sheets | `spreadsheets` | Reads and appends rows when asked. |

Pass `--scopes` with a comma-separated list to narrow it, or `--readonly` to try everything read-only first. Tokens are stored encrypted by `gws`, not in this folder. While the consent screen is in testing mode Google expires the sign-in after seven days, so expect to run `gws auth login` again now and then. `gws auth status` tells you where you stand.

### 5. Run

Double-click `dashboard\start-dashboard.bat`. It starts the server, waits for it to answer, then opens `http://127.0.0.1:7789`. The first start takes ten to fifteen seconds. Double-click `dashboard\stop-dashboard.bat` to stop it; the script checks that what is on the port is really this dashboard before doing anything. The server logs to `logs\server.log`.

From a terminal instead:

```
uv run python dashboard/server.py
```

### 6. First run

Click TALK once so the browser asks for the microphone and remembers the answer. Then type `/daily-planner` in the chat panel, or say "plan my day". With an empty state it has little to say, so add a task or two first, by voice or by typing. "Add a task: file the insurance claim by Friday" is enough.

## Talking to it

- **TALK** records until you click it again.
- **The ear button** turns on the wake word. Say "computer" and it listens. Audio is processed on your machine by openWakeWord; nothing is sent anywhere until the word fires.
- **The hotkey** does the same from any window, as long as the dashboard tab is open somewhere. Default `F8`. On a laptop `HOTKEY=<ctrl_r>` in `.env` gives you a single key with no Fn. The key still reaches whatever app is focused.
- After a spoken reply the microphone stays open for twelve seconds. Just keep talking. Silence closes it.
- Saying the wake word or pressing the hotkey while it is speaking or thinking interrupts it.
- Typing in the chat panel works too. Typed turns do not open the microphone.
- When the agent needs permission for something, or has a question with options, a card appears in the panel. Answer there.
- One session per day. Restarting the server resumes it. NEW SESSION starts over; old sessions stay on disk as Claude Code transcripts until `scripts/purge_sessions.py` removes them.

## Settings

All in `.env`, all optional except the three keys.

| Variable | Default | Meaning |
|---|---|---|
| `DEEPGRAM_MODEL` | `nova-3` | Speech to text model. |
| `CARTESIA_MODEL` | `sonic-3` | Text to speech model. |
| `CARTESIA_SPEED` | `0.90` | 0.6 to 1.5. |
| `CARTESIA_VOLUME` | `1.0` | 0.5 to 2.0. |
| `CARTESIA_EMOTION` | `sarcastic` | Any value Cartesia accepts. Empty lets the model read the text. |
| `WAKE_MODEL` | `models/wake/computer_v1.onnx` | A path, or a bundled name such as `hey_jarvis`. |
| `WAKE_THRESHOLD` | `0.5` | Lower if it misses you, raise if it fires on its own. |
| `WAKE_SILENCE_MS` | `3000` | Quiet time that ends a spoken turn. |
| `WAKE_MAX_MS` | `15000` | Longest single utterance. |
| `WAKE_SPEECH_RMS` | `0.02` | Loudness that counts as speech. |
| `FOLLOWUP_MS` | `12000` | Follow-up window after a reply. 0 turns it off. |
| `HOTKEY` | `<f8>` | pynput syntax. Empty turns it off. |
| `AGENT_MODEL` | `claude-sonnet-5-5` | Claude model for the session. |
| `DASH_PORT` | `7789` | Server port. |

## Safety

- The assistant cannot send email. A `PreToolUse` hook refuses any `gws gmail` send, reply or forward and tells the agent to create a draft instead. You press Send in Gmail. This holds in every permission mode.
- Writes to Docs, Drive and Sheets ask first, through a card in the panel. Calendar events for scheduled tasks are the one write that happens on its own; `CLAUDE.md` explains the rules.
- Every state write goes through `scripts/state.py`, and a hook blocks any edit to a state file that was not read first, so two writers cannot clobber each other.
- No secrets are in this repository. `.env` is gitignored, and Claude and Google credentials live in their own tools' stores, not here.
- Runs on localhost only.

## Making it yours

- `system-prompt.md` holds the whole system prompt, personality included. HTML comments in it are stripped before sending, so annotate freely. Changes take effect on the next server start.
- `CLAUDE.md` is the operating manual the agent reads every turn. The state schemas and planning rules are there.
- The skills in `.claude/skills/` are the morning plan, the weekly review and the end-of-day wrap-up. Edit them like any Claude Code skill.
- The assistant is called Compyutah in `dashboard/index.html`. Rename it in three places and in `state/dashboard.json`'s key if you like.
- Other wake words: `models/wake/` has `computer_v2.onnx` and `ok_computer.onnx`, openWakeWord bundles a few more, and its training notebook makes new ones in under an hour.

## Your data

`state/*.json` are tracked in git as empty templates so a fresh clone works. Once you add entries they will show up as changes. Keep your copy private, or tell git to ignore your edits:

```
git update-index --skip-worktree state/*.json
```

Conversation transcripts are written by Claude Code under your home folder, not here. `python scripts/purge_sessions.py` deletes the ones idle for thirty days or more; `--dry-run` lists them first.

## Keeping a public branch current

If you work on `main` with your own entries and share a `public` branch, do not merge or rebase between them. The public branch is an orphan with no history in common, and that is what keeps your private history private. `python scripts/sync_public.py` copies main's committed files into the public worktree, leaves out `state/*.json` and anything gitignored, checks the result with `scripts/scan_public.py`, and commits one snapshot. Put the words the scan must never find, your name and email for a start, in `private_terms.txt`, which is gitignored. `--dry-run` shows what would change without writing anything.

## License

MIT. See `LICENSE`.

## Credits

- [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) by Anthropic.
- [openWakeWord](https://github.com/dscripka/openWakeWord) by David Scripka, Apache 2.0.
- The "computer" wake word models come from [fwartner/home-assistant-wakewords-collection](https://github.com/fwartner/home-assistant-wakewords-collection), MIT. Their training notes are in `models/wake/README.md`.
- [gws](https://github.com/googleworkspace/cli), Google Workspace's CLI.
- Speech by [Deepgram](https://deepgram.com) and [Cartesia](https://cartesia.ai).
