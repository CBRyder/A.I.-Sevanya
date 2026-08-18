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
| — | `sync_repo` + `fetch_url` — reads GitHub repos and public pages ✅ |
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

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Offline and free: no API key, no network, and every `Store` is built on a
temp file, so a test run can't touch `~/.sevanya/sevanya.db`.

The suite is shaped by the bugs that actually happened, not by coverage. Two
of them cost a day each and both were one assert away from being caught:

- A tool schema with `input_Schema` instead of `input_schema`. The whole tools
  array is validated on **every** request, so one typo meant Sevanya couldn't
  answer "hello" — it looked like a grep bug and wasn't.
- A button whose handler named an id that wasn't in the markup. That throws at
  the top level of the script, which aborts the rest of it: send, restore, the
  thread picker, all dead, with no error visible on a phone.

`tests/test_web.py` checks the front end without a browser — every id the
script reaches for exists in the markup, no button is wired with bare
`getElementById().onclick=`, both script blocks parse under `node --check`
(skipped if node isn't installed), and the icons the manifest promises are on
disk.

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

## Reaching outside the machine

Two tools, both reads. She still has no way to write your source; a clone lands
in `~/.sevanya/repos`, her own cache, the same place the journal lives.

| tool | for |
|---|---|
| `sync_repo` | clone a GitHub repo, or update the copy she has |
| `fetch_url` | read a public page as text |

A synced repo is just a directory — `read_file`, `list_files` and `grep` all
work on it under `repos/owner/name/...`, which is the point of keeping a local
copy rather than reading files one at a time over the API.

```
you> how does the anthropic sdk handle streaming?
  [sync_repo {'repo': 'anthropics/anthropic-sdk-python'}]
  [grep {'pattern': 'text_stream', 'path': 'repos/anthropics/anthropic-sdk-python'}]
```

**Public hosts only.** She runs on your machine, on Tailscale, so "fetch this
URL" is also a route to your router's admin page or anything bound to
localhost. Every hostname is resolved and every address it answers with must be
public — all of them, not just the first — and the check runs again on each
redirect, because a public URL is free to redirect to `127.0.0.1`.

**Fetched text is data, not instructions.** A page can say "ignore your
previous instructions" as easily as anything else. Everything `fetch_url`
returns is labelled as web content, and `prompt.py` tells her the only person
whose instructions she follows is you.

Private repos aren't supported — cloning uses no credentials and
`GIT_TERMINAL_PROMPT=0`, so a private URL fails immediately instead of hanging
on a password prompt nobody is going to type.

## Layout

```
sevanya/
  agent.py    the loop — send() blocks, stream() yields
  server.py   FastAPI: /api/chat (SSE) + /api/ask (Siri)
  web/        single-page UI, installable to the iPhone home screen
  web/static/ app icons — without them iOS uses a screenshot of the page
  tools.py    what it's allowed to do (note what's absent)
  net.py      the two things that leave the machine, and what they refuse
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
- A path starting `repos/` addresses the clone cache, not your project — but
  if your project has its own top-level `repos/`, yours wins and `sync_repo`
  tells you the cache is shadowed rather than handing back a path that reads
  the wrong files.
- Updating a clone is `fetch` + `reset --hard`, not a merge. It's a read-only
  mirror; there's nothing local worth preserving, and a merge conflict in there
  is a mess nobody is going to resolve by hand.
- `MAX_STEPS` in `agent.py` caps tool calls per turn. If it trips, something
  is looping.
- `Store` opens **one connection per thread** — the web server runs requests in
  a threadpool and SQLite connections can't cross threads. Don't "simplify" it
  back to a single shared connection.
- **↻** re-pulls the current thread from the server. Worth having because the
  transcript changes without this device doing anything — ask Siri something
  with the page open and it lands in the database, not in the log. Note that
  tool lines don't come back: `/api/conversations/{id}` returns text only.
- Wire buttons with `bind(id, fn)`, not `getElementById(id).onclick`. If the
  id doesn't match the markup, the direct form throws at the top level of the
  script, which aborts **the rest of the script** — send stops working, the
  transcript stops loading, the whole page goes inert over one wrong string.
  `bind` reports the mismatch on screen and keeps binding everything else.
- The first `<script>` block puts JS errors *in the page*. There's no console
  on an iPhone, so a silent script death is otherwise undebuggable from the
  device. It's a separate block because a syntax error is thrown while its own
  script is compiling — a handler inside that script would never have run.
- The **Threads** button lists `/api/conversations`, Siri's included, so the
  phone can rejoin yesterday's thread. A thread the server doesn't have any
  more (`404`) clears itself from localStorage rather than leaving you typing
  into a conversation that no longer exists.
- `/api/chat` with no `conversation_id` starts a **new** thread, not the latest.
  Latest would drop me into whatever Siri last asked. The browser remembers its
  own id in localStorage.
