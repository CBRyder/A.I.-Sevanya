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
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import Agent
from .store import Store
from .tools import PROJECT_ROOT

WEB_DIR = Path(__file__).parent / "web"

# Set SEVANYA_TOKEN to require a bearer token. Over Tailscale nothing else can
# reach this anyway, but a token costs nothing and means one misconfigured
# firewall rule isn't the only thing standing between the internet and a shell
# on your machine.
TOKEN = os.environ.get("SEVANYA_TOKEN")

# Appended to the system prompt for /ask only. Siri reads the reply aloud, and
# anything longer than a few sentences is unbearable through a speaker.
SPOKEN = """
You are being read aloud by a voice assistant. Answer in two or three sentences
of plain prose. No code blocks, no bullet lists, no file paths unless the answer
is meaningless without one. If the honest answer needs more room than that, give
the short version and say the detail is worth looking at on a screen.
"""

app = FastAPI(title="Sevanya")
store = Store()

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
    # 0.0.0.0 so your phone can reach it over Tailscale. On a machine that is
    # NOT on a private network, this listens on every interface — set a token.
    uvicorn.run(app, host="0.0.0.0", port=8765)


if __name__ == "__main__":
    main()
