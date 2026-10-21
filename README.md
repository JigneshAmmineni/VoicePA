# VoicePA

VoicePA is a personal assistant you talk to out loud. Say "computer" or press a key, tell it what's on your mind, and it answers in a sentence or two. It keeps track of your tasks, habits and priorities, plans your morning around your calendar and inbox, books time for your work on your calendar, and walks you through an end-of-day wrap-up and a weekly review. Everything it knows about you lives in plain files on your own computer.

## What it can do

**Tasks.** Add, update and finish tasks by voice. Each task can carry a priority, an urgency, a rough size, a due date and a day it's scheduled for. Tasks you're blocked on are tracked as "waiting" and come back as follow-up reminders instead of cluttering your to-do list, and tasks you want to keep but not think about can be put into hibernation.

**Priorities.** A short list of what matters most right now. Priorities sit at the top of the dashboard and decide which tasks get picked first each day. If everything is a priority, nothing is, so it makes you choose.

**Habits.** Daily habits with streaks. They sit right on the dashboard, and you can check one off with a click or just by saying so.

**Calendar scheduling.** When you give a task a day, it books time for it on your Google Calendar on its own. It schedules intelligently, considering what's already on the calendar and what the task demands, then tells you when it landed and what it sits next to.

**Morning planner.** Say "plan my day" and it reads your calendar, sorts your inbox into what needs a reply and what can wait, checks your priorities, habits and deadlines, and builds a realistic plan for the day without overloading it. You hear the one thing that matters most; the full plan is on the dashboard.

**Night wrap-up.** Say "good night" or "done for the day" and it reviews what got done and what didn't, logs your habits, and resets for tomorrow. Unfinished work is never silently moved around.

**Journal.** At the end of the day it asks if anything's worth writing down, and records what you say word for word.

**Weekly review.** Habit consistency, what got done, what you kept putting off, tasks that have gone stale, and anything your journal suggests about where your focus should go. It ends by helping you reset your priorities for the week ahead.

**Email.** Summarizes your inbox and drafts replies at your command. It cannot send email: drafts wait in Gmail for you to read and send.

**Everything else worth keeping.** Ideas, side projects, papers and things to read, a shopping list that tracks things to buy, return and sell along with their deadlines, and a watchlist that recommends something to watch based on your mood. It can also read and add to your Google Docs, Drive and Sheets when asked, and it remembers your preferences and long-term goals between conversations.

**Personality.** It keeps replies short and has a dry, sarcastic sense of humor by default. The whole personality is one paragraph you can rewrite.

## Talking to it

- **Wake word.** Turn on the ear button and say "computer". Listening for the wake word happens on your computer; nothing is sent anywhere until it hears it.
- **Hotkey.** Press `F8` from any app to start talking. The dashboard tab just needs to be open somewhere. You can change the key, or turn it off, with `HOTKEY` in `.env` (see Settings).
- **TALK button**, or type in the chat panel.
- After it answers, the microphone stays open for twelve seconds so you can keep going without the wake word. Silence closes it.
- Say the wake word or press the hotkey while it's talking to interrupt it.
- When it needs your permission, or has a question with options, a card appears in the chat panel.
- One conversation per day, picked back up if you restart. NEW SESSION starts fresh.

## How it works

VoicePA runs a Claude agent on your machine, built on the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python). A small local web server owns the conversation and serves a single-page dashboard. Your speech goes to Deepgram to become text, the agent reads and updates your data and your Google account through Google's [`gws`](https://github.com/googleworkspace/cli) command-line tool, and the reply is spoken back by Cartesia. The agent's behavior is described in plain language in `CLAUDE.md`, `system-prompt.md` and three skills under `.claude/skills/`, so changing how it works mostly means editing text.

| Path | What it is |
|---|---|
| `dashboard/` | The local server, the agent session and the dashboard page, plus double-click start and stop scripts. |
| `state/` | Your data, as JSON. Ships empty. |
| `scripts/` | The tools the agent uses to update your data safely, and the safety hooks. |
| `.claude/` | Permissions, hooks, and the morning planner, wrap-up and weekly review skills. |
| `CLAUDE.md` | The assistant's operating manual. |
| `system-prompt.md` | The system prompt, including the personality. |
| `models/wake/` | The "computer" wake word models. |

## Requirements

Setup takes about half an hour, most of it creating accounts. If you use a coding agent such as Claude Code, open this folder in it and ask it to walk you through the steps below; it can do most of them for you.


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

- It cannot send email. A hook blocks every send, reply and forward and has it make a draft instead, whatever permission mode it runs in.
- Changes to Docs, Drive and Sheets ask first, through a card in the chat panel. Calendar events for scheduled tasks are the one thing it writes on its own.
- A hook stops it from overwriting a data file it hasn't just read, so the dashboard and the agent can't clobber each other.
- No secrets live in this repository. `.env` is gitignored, and Claude and Google sign-ins live in their own tools' stores.
- The server only listens on your own machine.

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

## License

MIT. See `LICENSE`.

## Credits

- [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) by Anthropic.
- [openWakeWord](https://github.com/dscripka/openWakeWord) by David Scripka, Apache 2.0.
- The "computer" wake word models come from [fwartner/home-assistant-wakewords-collection](https://github.com/fwartner/home-assistant-wakewords-collection), MIT. Their training notes are in `models/wake/README.md`.
- [gws](https://github.com/googleworkspace/cli), Google Workspace's CLI.
- Speech by [Deepgram](https://deepgram.com) and [Cartesia](https://cartesia.ai).
