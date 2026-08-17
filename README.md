# Sevanya

A programming mentor that runs on my own machine and reaches my phone.

Built to teach rather than to autocomplete: it can read my code and run things,
but it has no tool that writes to my source files. The constraint is
structural, not a promise in a prompt.

## Status

**Stage 2 — conversations persist and it keeps a journal.**

| | |
|---|---|
| 1 | Agent loop + tools, terminal ✅ |
| 2 | SQLite persistence + learning journal ✅ |
| 3 | FastAPI — `/chat` (SSE, web UI) + `/ask` (blocking, for Siri) |
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

## Layout

```
sevanya/
  agent.py    the loop — model call, tool dispatch, repeat
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
- **Thread policy:** every Siri request starts a fresh conversation. Continuity
  comes from `recall` searching history, not from carrying a transcript. If it
  can't find what I'm referring to it asks, rather than guessing.
- `MAX_STEPS` in `agent.py` caps tool calls per turn. If it trips, something
  is looping.
