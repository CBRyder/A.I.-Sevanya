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
| — | task list — she adds, completes and drops them ✅ |
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

Run it from the directory you want it to be able to read. The server entry
point checks `requirements.txt` and installs anything missing **before** it
imports anything that needs it, so a fresh clone or a new line in the file just
works:

```bash
python -m sevanya              # the server: checks requirements, then serves
```

Set `SEVANYA_SKIP_DEPS=1` to start without checking, for working offline or
managing the environment yourself. `SEVANYA_PORT` moves it off 8765.

The terminal REPL:

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
python -m sevanya
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
| `GET /api/health` | the restart flow | is it up, does it want a token — no auth |
| `GET /api/notifications` | Notices | the log, newest first |
| `GET /api/db` | Data | schema state, counts, backups |
| `POST /api/db/backup` | Data | take a backup |
| `POST /api/db/clear-history` | Data | delete chats, keep the journal |
| `GET /api/conversations` | both | recent threads |
| `GET /api/conversations/{id}` | both | readable transcript |

## Her list

`task_list` in the same SQLite database. **It's hers, not mine.** She decides
what goes on it — a gap she noticed, a concept I nearly have, a fix worth
making properly — and she marks things off. I can read it. I can't edit it.

That's the whole point. A list I could edit would drift into a list of what I
already felt like doing, which I don't need her for.

| tool | for |
|---|---|
| `add_task` | something she's decided I should do |
| `complete_task` | I did it |
| `remove_task` | it stopped mattering — permanent, and not the same as done |
| `list_tasks` | the whole list, completed ones included |

The **Tasks** button in the web UI shows it, read-only: no checkboxes, no
delete. `GET /api/tasks` is the only endpoint, and there's a test asserting no
write endpoint appears, so adding one has to be a deliberate decision rather
than a two-line drift.

Open tasks are injected into the system prompt the way recent journal notes
are, so she starts every conversation knowing what's outstanding — with the
ids, since completing one needs an id and she shouldn't have to look it up
first. Capped at ten; the context window isn't free.

Different from the journal, which is what she noticed about how I'm learning
and is written once. This has a lifecycle.

## Telling her to reload

"Reload" works as a thing I say to her, not just a button I press. The `reload`
tool checks `requirements.txt`, installs anything missing, restarts the server,
and my browser notices and reloads itself — so front-end changes show up too,
not just Python ones.

`python -m sevanya` runs the same check on the way up, and this is why it's a
separate entry point rather than a few lines in `server.py`: `server.py`
imports fastapi at the top, so if fastapi is missing the process is already
dead before any of our code runs, and a check there could only ever confirm
what already worked. The bootstrap touches nothing outside the standard library
until the requirements are known good.

The dependency check asks two questions, and the second is the one that bites:

- is it installed, at a version the requirement allows?
- **does it actually import?**

A package can be present, correct, and still fail on import because something
underneath it isn't there. That surfaces as the server dying at startup with a
traceback naming a module I've never heard of, rather than as "you're missing a
dependency" — much worse to debug from a phone.

If the check fails, **she doesn't restart**. The process would come back only
far enough to crash on import, and then there's nothing listening to explain
why. She reports what's wrong and stays up instead.

A restart goes back through the bootstrap, so a reload picks up a changed
`requirements.txt` before importing anything that needs it. `server.py` keeps
its own check as a backstop for anyone starting the module directly, and
records the answer either way, so a start into a broken environment leaves
evidence.

## Reaching my phone

She can push a notification to my phone through [ntfy](https://ntfy.sh),
**self-hosted**. What she'd be telling me about is what I'm building, and that
shouldn't be passing through a machine I don't run.

```bash
docker compose -f deploy/ntfy-compose.yml up -d
docker exec -it sevanya-ntfy ntfy user add --role=admin sevanya
docker exec -it sevanya-ntfy ntfy token add sevanya
```

```bash
export SEVANYA_NTFY_SERVER=http://<tailscale-name>:8080
export SEVANYA_NTFY_TOPIC=some-long-unguessable-string
export SEVANYA_NTFY_TOKEN=tk_...
```

Then point the ntfy app at the same server over Tailscale and subscribe. The
compose file sets `auth-default-access: deny-all`, which is the part not to
skip: without it anyone who reaches port 8080 can both read my notifications
and send me fake ones.

The public ntfy.sh still works if I leave `SEVANYA_NTFY_SERVER` unset, and
she'll drop a notice at startup saying so — no accidental drift back onto
someone else's server.

**The topic name is the password** either way: anyone who knows it can read the
notifications and publish to them. It's never printed in a log line or an
error, and `push.where()` reports the server only.

She pushes in three cases:

- **when she decides it's worth it** — the `notify_phone` tool. The prompt tells
  her to be sparing: a buzz that wasn't worth reading teaches me to ignore the
  next one, and the next one might be the one that mattered.
- **when something failed that I'd otherwise only find by walking to the PC** —
  a reload that couldn't fix the requirements, a server that started wrong.
  Not on success: the page comes back by itself and I'm already looking at it.
- **when she ticks something off her list.**

Unlike `fetch_url`, this URL is mine rather than the model's, so it doesn't go
through `net.check_url` — a self-hosted ntfy on my own network is exactly the
setup that check refuses, and rightly so for an address the model picked.

A push failing never breaks what she was doing. Most of them happen while
something is already going wrong, and a failed notification becoming the new
exception turns "the reload failed" into "the reload crashed". Every attempt is
recorded either way, because a push that silently didn't arrive is worse than
one that never existed — I'd be sitting there assuming I'd have been told.

## When I've been away

If I haven't written anything for 24 hours, she writes me a short check-in —
looks at what's open on her list and what I was last doing, picks the one thing
most worth coming back to. It lands as its own `check-in` thread and as a
notification.

She keeps nudging every 24 hours until I actually reply. Away for a week, come
back to seven — deliberate, since the alternative is one message on day two
that I never see.

```bash
SEVANYA_CHECKIN=0          # turn it off
SEVANYA_CHECKIN_HOURS=48   # or make it less eager
```

A conversation has to open with a user turn — the API rejects one starting with
the assistant — so the thread begins with a synthetic prompt marked
`[sevanya:auto]`, which the transcript endpoint hides. She sees it, because it's
the instruction; I don't, because it isn't something I said.

Two things that took care and are worth not undoing:

- Her own check-in is stored with role `user`, so it must not count as *me*
  talking. If it did she'd nudge once, see her own message, conclude I'd come
  back, and go quiet forever.
- The `checkin` notice is recorded before the push and regardless of whether it
  worked. It's what tells her she's already nudged, so a phone that's turned
  off would otherwise mean a check-in every ten minutes.

## Notices

`notifications` in the same database — restarts, dependency checks, errors:
things that happened on the machine while I wasn't looking at it, which is the
normal case when she's on the PC and I'm on the phone.

The **Notices** button opens the log, scrollable and read-only, with a count of
what's arrived since this device last looked. "Seen" is tracked in
`localStorage`, because it's a property of the phone rather than of the notice —
and marking one read on the server would be a write to a log that only reads.
`GET /api/notifications` is the only endpoint, and the log is trimmed to the
most recent 500 so it can't grow forever in the same database as the journal.

## Restarting it from the phone

**⏻** in the web UI restarts the server process — for when it's wedged and I'm
not at the machine. It asks first, then waits for the server to genuinely come
back before saying so.

`POST /api/restart` schedules an `os.execv` and returns *before* replacing the
process: restarting inline would drop the connection mid-request, which looks
exactly like the button not working. Same PID afterwards, since execv replaces
the image rather than spawning a child — which is why `/api/health` reports
`started`. The pid can't tell "it restarted" from "nothing happened"; the start
time can, and the UI polls on it rather than on any 200, because for a moment
the server that's about to die is still answering.

It requires the token when one is set — it's the only endpoint that does
something to the machine rather than reading from it. With no token set,
anything that can reach the port can bounce the server.

The relaunch is always `python -m sevanya.server`, whatever was typed
originally, because `python server.py` can't work — the relative imports need
the package context that `-m` provides. cwd and the environment survive the
exec, so `PROJECT_ROOT` and `SEVANYA_TOKEN` are the same on the other side.
Set `SEVANYA_PORT` if 8765 isn't wanted. A reply still streaming is lost;
conversations and the list are on disk and unaffected.

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
  deps.py     are the requirements installed — and do they import
  push.py     sending a notification to the phone
  checkin.py  the nudge after a day of quiet
  lifecycle.py  restarting the process, shared by the endpoint and the tool
  __main__.py   `python -m sevanya` — requirements first, then the server
  store.py    SQLite: conversations, messages, journal, task list
  migrations.py  schema versioning and the drift check
  db.py       maintenance CLI: check, backup, migrate, clear-history
  prompt.py   the teaching contract
  main.py     terminal REPL
```

## Looking after the database

**From the phone — the Data button.** It shows what `check` prints (counts,
schema version, drift, unloadable rows, recent backups) and does the two things
worth doing: back up, and clear the chat history. The confirmation happens in
the page. Answering a terminal prompt on the PC defeats the point of running
this on the phone.

| endpoint | |
|---|---|
| `GET /api/db` | everything `check` prints, as JSON |
| `POST /api/db/backup` | a WAL-safe copy |
| `POST /api/db/clear-history` | needs `{"confirm": true}` — always backs up first |

`confirm` is not implied by having made the request, and there is deliberately
no way to skip the backup over HTTP. On the command line you're standing at the
machine and can insist; from a phone, one mis-tap shouldn't be the end of the
transcripts. Clearing is recorded in the notices, naming the backup it took.

**From the machine**, the same things:

```bash
python -m sevanya.db check           # version, drift, contents, unloadable rows
python -m sevanya.db backup          # WAL-safe copy
python -m sevanya.db migrate         # apply pending schema changes
python -m sevanya.db clear-history   # delete chats, keep the journal and the list
```

**Before any overhaul, run `backup`.** One second, and everything after it is
reversible.

### Clearing history keeps what she learned

`clear-history` deletes conversations and messages. The journal, the task list
and the notices stay. That works because `journal` and `task_list` reference
conversations `ON DELETE SET NULL` while `messages` is `ON DELETE CASCADE` — so
removing a thread takes its transcript and leaves her notes standing with the
link blanked. It only holds with foreign keys enforced, which is set on every
connection; don't remove that pragma.

It asks first and takes a backup before deleting. `--keep-days 7` keeps recent
threads; `--yes` skips the prompt.

### CREATE TABLE IF NOT EXISTS is not a migration

`IF NOT EXISTS` means *table*, not *schema*. SQLite sees the table is there and
stops reading — it never compares the definition against the real one. So a
change that adds or renames a column lands in `store.py`, does nothing to the
database, and says nothing until an INSERT that looks obviously correct dies
with `no such column`, hours later and nowhere near the cause.

So schema changes go through `migrations.py`: an explicit `ALTER`, against a
version number, run once. Editing `SCHEMA` alone does nothing to a database
that already exists.

And in case someone forgets, `Store` **refuses to open** a database whose
columns don't match what the code expects, with a message naming the missing
column. A clear failure at startup beats a puzzling one at the first write.

### Old rows keep their old shape

Message content is stored as JSON and read back as whatever shape it went in
as. Change the shape and old rows still hold the old one, so reopening an old
conversation breaks in a way that has nothing to do with the new code.
`check` finds those rows before they find you; `clear-history` removes them
along with the threads they're in.

### Why `.backup` and not `cp`

`journal_mode` is WAL, so recent commits can still be sitting in
`sevanya.db-wal` rather than the main file. Copying the one file can silently
lose the newest notes — in the test that pins this, with the WAL never
checkpointed, the naive copy has **no tables at all**. `store.backup()` uses
SQLite's own backup, which folds the WAL in and is safe while something else is
writing.

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
- `reload` refuses to restart when the requirements are wrong. Coming back far
  enough to crash on import is worse than not restarting, because then nothing
  is listening to say what happened.
- `tests/test_restart.py` starts a real server and restarts it for real. It's
  the slow test, and the only one that would catch a restart that kills the
  process and never brings it back — the failure that ends with me walking to
  the machine.
- The `task_list` table is created with `IF NOT EXISTS` like the rest of the
  schema, so an existing `~/.sevanya/sevanya.db` picks it up on next start.
  There's no migration to run.
- `complete_task` and `remove_task` are deliberately different: one is history,
  the other is gone. Given a task id that doesn't exist, both answer with the
  actual open list rather than just refusing — the id was probably misread.
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
