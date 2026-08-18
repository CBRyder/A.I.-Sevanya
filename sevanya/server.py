"""HTTP server — the piece your phone talks to.

Two endpoints, deliberately different in shape:

  POST /api/chat   streams tokens as they arrive. For the web UI, where you
                   want to watch it think.

  POST /api/ask    blocks, returns one blob of text. For Siri, which cannot
                   consume a stream — a Shortcut sends one request, waits, and
                   speaks whatever comes back.

Everything intelligent stays here on the PC. The phone is a thin client.
"""

import json
import os
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import deps, lifecycle
from .agent import Agent
from .store import Store
from .tools import PROJECT_ROOT

WEB_DIR = Path(__file__).parent / "web"

# Set SEVANYA_TOKEN to require a bearer token. Over Tailscale nothing else can
# reach this anyway, but a token costs nothing and means one misconfigured
# firewall rule isn't the only thing standing between the internet and a shell
# on your machine.
TOKEN = os.environ.get("SEVANYA_TOKEN")

# 8765 unless told otherwise. Configurable mostly so a second copy — a test,
# or a throwaway one pointed at another project — doesn't have to fight the
# one you actually use for the port.
PORT = int(os.environ.get("SEVANYA_PORT", "8765"))

# Appended to the system prompt for /ask only. Siri reads the reply aloud, and
# anything longer than a few sentences is unbearable through a speaker.
SPOKEN = """
You are being read aloud by a voice assistant. Answer in two or three sentences
of plain prose. No code blocks, no bullet lists, no file paths unless the answer
is meaningless without one. If the honest answer needs more room than that, give
the short version and say the detail is worth looking at on a screen.
"""

# When this process image started. execv keeps the PID, so the pid alone can't
# tell "it restarted" from "nothing happened" — this can, and the restart
# button uses it to confirm the server really came back rather than never
# having gone away.
STARTED = time.time()

app = FastAPI(title="Sevanya")
store = Store()

# Tells the `reload` tool there's a server here to restart. The terminal REPL
# never imports this module, so there it correctly reports nothing to do.
lifecycle.mark_server_running()

# Check the requirements on the way up and record the answer. Doing it here
# rather than only in `reload` means a restart that lands in a broken
# environment leaves a note saying so — otherwise the only evidence is a
# traceback in a terminal nobody is looking at.
_deps_ok, _deps_report = deps.ensure(PROJECT_ROOT, install_missing=False)
store.notify("startup", f"server started — {_deps_report}")
store.trim_notifications()

# App icons, referenced by manifest.json and the apple-touch-icon link. iOS
# will happily "Add to Home Screen" without them and give you a blurry
# screenshot of the page as the icon, which looks like something half-built.
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")


class ChatIn(BaseModel):
    message: str
    conversation_id: int | None = None


class AskIn(BaseModel):
    message: str


def _auth(authorization: str | None) -> None:
    if not TOKEN:
        return
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="bad or missing token")


@app.post("/api/chat")
def chat(body: ChatIn, authorization: str | None = Header(default=None)):
    """Streaming chat for the web UI.

    Server-Sent Events: one JSON object per line, prefixed `data: `. The browser
    reads them as they arrive rather than waiting for the whole reply.
    """
    _auth(authorization)

    # No id supplied means a new thread. Deliberately *not* "latest" — Siri
    # creates its own conversations, and grabbing the newest would drop you
    # into a voice thread the moment you opened the web UI. The browser
    # remembers its own conversation id instead (localStorage) and sends it.
    conversation_id = body.conversation_id
    if conversation_id is None:
        # Title it from the opening message, the way the REPL does. Without
        # this every thread the browser starts is "(untitled)" in the picker,
        # which makes the picker useless for the one job it has.
        conversation_id = store.new_conversation(title=body.message[:60])
    agent = Agent(store, conversation_id)

    def events():
        # Tell the client which conversation this is, so a phone that didn't
        # specify one can keep using the same thread on its next message.
        yield f"data: {json.dumps({'type': 'conversation', 'id': conversation_id})}\n\n"
        try:
            for kind, payload in agent.stream(body.message):
                yield f"data: {json.dumps({'type': kind, 'text': payload})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'text': f'{type(exc).__name__}: {exc}'})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/ask")
def ask(body: AskIn, authorization: str | None = Header(default=None)):
    """One-shot endpoint for Siri.

    Every request starts a **fresh conversation**, by design. Continuity comes
    from `recall` searching the journal and past transcripts when you refer to
    something — not from dragging a whole transcript along. That keeps a voice
    question from polluting the context of a coding session you have open at
    your desk.
    """
    _auth(authorization)

    conversation_id = store.new_conversation(title=f"siri: {body.message[:50]}")
    agent = Agent(store, conversation_id, system_extra=SPOKEN)
    return {"reply": agent.send(body.message), "conversation_id": conversation_id}


@app.get("/api/health")
def health():
    """Is the server there, and does it want a token?

    Deliberately the one endpoint that doesn't require auth. The client needs
    to tell "the server is gone" apart from "the server is fine and my token is
    wrong", and it can't do that if the check itself returns 401 in both cases.
    It reveals only whether a token is needed, which anyone who can reach this
    port finds out from their first request anyway.
    """
    return {"ok": True, "auth_required": bool(TOKEN), "started": STARTED}


@app.post("/api/restart")
def restart(authorization: str | None = Header(default=None)):
    """Restart the server process.

    Requires the token when one is set — this is the one endpoint that does
    something to the machine rather than reading from it. With no token set,
    anything that can reach the port can bounce the server; that's the same
    exposure as every other endpoint here, but it's worth knowing.

    In-flight streams die with the old process. The client polls /api/health
    and picks its thread back up from the database, which is on disk and
    unaffected.
    """
    _auth(authorization)
    lifecycle.schedule_restart()
    return {"restarting": True, "pid": os.getpid()}


@app.get("/api/notifications")
def notifications(authorization: str | None = Header(default=None)):
    """What's happened to her lately — restarts, installs, errors.

    Read-only, like the task list: this is a log of things that happened, and
    there is nothing here for a client to change.
    """
    _auth(authorization)
    return [dict(row) for row in store.notifications()]


@app.get("/api/tasks")
def tasks(include_done: bool = True, authorization: str | None = Header(default=None)):
    """The task list, for reading.

    Read-only by design: this is Sevanya's list of what she thinks you should
    do, not a to-do app you fill in. There's no endpoint to add or tick one
    off from the phone, because the list means nothing if it's yours.
    """
    _auth(authorization)
    return [dict(row) for row in store.list_tasks(include_done=include_done)]


@app.get("/api/conversations")
def conversations(authorization: str | None = Header(default=None)):
    _auth(authorization)
    return [dict(r) for r in store.list_conversations(limit=25)]


@app.get("/api/conversations/{conversation_id}")
def history(conversation_id: int, authorization: str | None = Header(default=None)):
    """Readable transcript, for a phone rejoining a conversation.

    Tool plumbing is stripped — the phone wants the conversation, not the
    tool_use blocks that made it work.
    """
    _auth(authorization)

    # Say plainly that it's gone, rather than returning []. A phone holding a
    # stale id in localStorage needs to be able to tell "empty conversation"
    # from "that conversation no longer exists" so it can drop the id.
    if not store.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail="no such conversation")

    out = []
    for message in store.load_messages(conversation_id):
        content = message["content"]
        if isinstance(content, str):
            text = content
        else:
            text = "\n".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        if text.strip():
            out.append({"role": message["role"], "text": text})
    return out


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/manifest.json")
def manifest():
    return FileResponse(WEB_DIR / "manifest.json")


def main() -> None:
    import uvicorn

    print(f"Sevanya server — reading from {PROJECT_ROOT}")
    print(f"auth: {'bearer token required' if TOKEN else 'OPEN (set SEVANYA_TOKEN to lock)'}")
    print(f"listening on :{PORT}")
    # 0.0.0.0 so your phone can reach it over Tailscale. On a machine that is
    # NOT on a private network, this listens on every interface — set a token.
    uvicorn.run(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
