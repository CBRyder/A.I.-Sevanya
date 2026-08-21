"""Naming a conversation from what you actually said, not truncating it.

`message[:60]` used to be the whole mechanism -- whatever fell in the first
60 characters, cut wherever that landed, mid-word if it had to. "Should we
use fetch_url or grep for th" isn't a title, it's a stump.

A real title costs one small model call. Worth it because a truncated
opening line is what sits in the conversation list forever afterward --
named once, at creation, never revisited.
"""

from . import subagent

SYSTEM = """\
Give this message a short title for a conversation list: three to six words,
plain text, no quotes, no punctuation at the end, no "Title:" prefix. Name
what the conversation is about, not the message's grammar. If the message is
too short or vague to name on its own (a greeting, a one-word reply), do
your best to name the likely topic rather than refusing or describing the
message itself.
"""

# A title this long has stopped being a title. Also the fallback's length,
# so a truncated raw message and a misbehaving model land on the same cap.
MAX_TITLE = 60


def generate(message: str, backend=None) -> str:
    """A short title for `message`, or a truncated fallback if that fails.

    Never raises -- a broken title generator isn't a reason a conversation
    can't start, and the caller shouldn't have to wrap this in its own
    try/except to remember that. `backend` is only for tests; real callers
    get subagent.backend_for_subagents(), the same small-job routing that
    already exists for delegated reading -- naming a conversation is that
    same category of work, not worth the conversation's own model.
    """
    fallback = message[:MAX_TITLE]
    try:
        backend = backend or subagent.backend_for_subagents()
        reply = backend.send(SYSTEM, [{"role": "user", "content": message}], [])
        title = reply.text().strip().strip('"').strip("'").strip()
    except Exception:
        return fallback
    return (title or fallback)[:MAX_TITLE]
