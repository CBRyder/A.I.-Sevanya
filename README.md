# Sevanya

A programming mentor that runs on my own machine and reaches my phone.

Built to teach rather than to autocomplete: it can read my code and run things,
but it has no tool that writes to my source files. The constraint is
structural, not a promise in a prompt.

## Status

**Stage 1 — terminal agent loop.** Working. Reads files, answers questions, no
persistence yet.

| | |
|---|---|
| 1 | Agent loop + tools, terminal ✅ |
| 2 | SQLite persistence + learning journal |
| 3 | FastAPI + web UI + streaming |
| 4 | Tailscale, phone access |
| 5 | Teaching modes, sharper tools |

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...   # Windows: set ANTHROPIC_API_KEY=...
```

Run it from the directory you want it to be able to read:

```bash
python -m sevanya.main
```

## Layout

```
sevanya/
  agent.py    the loop — model call, tool dispatch, repeat
  tools.py    what it's allowed to do (note what's absent)
  prompt.py   the teaching contract
  main.py     terminal REPL
```

## Notes to self

- `PROJECT_ROOT` is the directory you launch from. Nothing outside it is
  readable — `tools._resolve` enforces that.
- The conversation lives in `Agent.messages` and dies with the process.
  That's stage 2.
- `MAX_STEPS` in `agent.py` caps tool calls per turn. If it trips, something
  is looping.
