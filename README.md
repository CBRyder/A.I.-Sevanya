# Sevanya

A programming mentor that runs on my own machine and reaches my phone.

Built to teach rather than to autocomplete: it can read my code and run things,
but it has no tool that writes to my source files. The constraint is
structural, not a promise in a prompt.

## Status

**Stage 3 — HTTP server, web UI, ready for the phone.**

| | |
|---|---|
| 1 | Agent loop + tools, terminal ✅ |
| 2 | SQLite persistence + learning journal ✅ |
| — | grep tool (mine) ✅ |
| 3 | FastAPI — `/api/chat` (SSE) + `/api/ask` (blocking, Siri) ✅ |
| 4 | Tailscale + iOS Shortcut → "Hey Siri, ask Sevanya…" |
| 5 | Expo Go client, if the PWA isn't enough |
| 6 | Local model via LM Studio, teaching modes |

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...   # Windows: set ANTHROPIC_API_KEY=...
```

Run it from the directory you want it to be able to read:

```bash
python -m sevanya.main          # resume where I left off
python -m sevanya.main --new    # fresh conversation
python -m sevanya.main --list   # what have I got
python -m sevanya.main --id 7   # jump to one
```

## Server (for the phone)

```powershell
$env:SEVANYA_TOKEN = "some-long-random-string"   # optional but do it
python -m sevanya.server
```

Then `http://localhost:8765` in a browser, or `http://<tailscale-name>:8765`
from my phone. Add to Home Screen for the app-like version.

If a token is set, the web UI asks for it the first time a request comes back
401, and keeps it on the device. No console needed — iOS Safari doesn't have
one, which is the whole point. `http://host:8765/?token=...` also works, for a
QR code or a Shortcut; the token is saved and stripped from the URL.

| endpoint | for | shape |
|---|---|---|
| `POST /api/chat` | web UI | SSE, streams as it thinks |
| `POST /api/ask` | Siri Shortcut | blocking, one blob of text |
| `GET /api/conversations` | both | recent threads |
| `GET /api/conversations/{id}` | both | readable transcript |

## Layout

```
sevanya/
  agent.py    the loop — send() blocks, stream() yields
  server.py   FastAPI: /api/chat (SSE) + /api/ask (Siri)
  web/        single-page UI, installable to the iPhone home screen
  web/static/ app icons — without them iOS uses a screenshot of the page
  tools.py    what it's allowed to do (note what's absent)
  store.py    SQLite: conversations, messages, journal
  prompt.py   the teaching contract
  main.py     terminal REPL
```

## Notes to self

- `PROJECT_ROOT` is the directory you launch from. Nothing outside it is
  readable — `tools._resolve` enforces that.
- Memory lives in `~/.sevanya/sevanya.db`, **not** in the repo — it follows me
  across projects. Back it up; it's the part that isn't replaceable.
- Message content is stored as JSON blocks, not text, so `tool_use` survives a
  reload. See the comment on `store._jsonable` before "simplifying" it.
- The journal is written by Sevanya via `remember`, not by me. Five most recent
  notes get injected into the system prompt; older ones it has to `recall`.
- `recall` searches the journal **and** past conversation text. Tool results are
  excluded — they're file dumps, and matching inside them is noise.
- `grep` is literal and case-insensitive, **not** a regex — an identifier with a
  `.` or `(` in it shouldn't turn into pattern syntax. It caps at
  `MAX_MATCHES` hits and skips build dirs, dotfiles and anything that isn't
  UTF-8.
- **Thread policy:** every Siri request starts a fresh conversation. Continuity
  comes from `recall` searching history, not from carrying a transcript. If it
  can't find what I'm referring to it asks, rather than guessing.
- `MAX_STEPS` in `agent.py` caps tool calls per turn. If it trips, something
  is looping.
- `Store` opens **one connection per thread** — the web server runs requests in
  a threadpool and SQLite connections can't cross threads. Don't "simplify" it
  back to a single shared connection.
- The **Threads** button lists `/api/conversations`, Siri's included, so the
  phone can rejoin yesterday's thread. A thread the server doesn't have any
  more (`404`) clears itself from localStorage rather than leaving you typing
  into a conversation that no longer exists.
- `/api/chat` with no `conversation_id` starts a **new** thread, not the latest.
  Latest would drop me into whatever Siri last asked. The browser remembers its
  own id in localStorage.
