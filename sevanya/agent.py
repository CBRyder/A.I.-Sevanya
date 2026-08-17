"""The agent loop.

This is the whole idea. Everything else in this project — the database, the
web server, the phone access — is plumbing around these forty lines.

The model cannot run anything. When it wants a tool, it emits a structured
block saying so and stops. Your code runs the function, appends the result to
the conversation, and calls the model again. Repeat until it stops asking.
That's what makes an "agent" rather than a chatbot.
"""

import anthropic

from . import tools
from .prompt import SYSTEM
from .store import Store

MODEL = "claude-opus-5"

# A runaway loop is a runaway bill. If it's made this many tool calls without
# arriving at an answer, something is wrong and you want to know about it.
MAX_STEPS = 12


class Agent:
    def __init__(
        self,
        store: Store,
        conversation_id: int,
        client: anthropic.Anthropic | None = None,
    ):
        self.client = client or anthropic.Anthropic()
        self.store = store
        self.conversation_id = conversation_id

        # The conversation. The API is stateless — the model remembers nothing
        # between calls — so this list *is* Sevanya's memory of the session,
        # and gets re-sent in full on every single turn.
        #
        # Loading it from SQLite is the entire trick behind resuming a session,
        # and later behind picking up on your phone where you left off at your
        # desk. There is no server-side session to reconnect to; you just
        # replay the transcript.
        self.messages: list[dict] = store.load_messages(conversation_id)

    def _system(self) -> str:
        """System prompt plus a little continuity from the journal.

        Injecting the few most recent notes costs almost nothing and means
        Sevanya opens knowing roughly where you left off, rather than needing
        to call `recall` before it can be useful. Anything older it has to go
        looking for — which is the right default, since old notes shouldn't
        crowd the context window forever.
        """
        recent = self.store.recent_journal(limit=5)
        if not recent:
            return SYSTEM
        lines = "\n".join(f"- [{r['topic']}] {r['note']}" for r in reversed(recent))
        return f"{SYSTEM}\n\nFrom your journal, most recent last:\n{lines}\n"

    def send(self, user_text: str) -> str:
        """Send one user message, run any tools it triggers, return the reply."""
        self._record("user", user_text)

        for _ in range(MAX_STEPS):
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=self._system(),
                tools=tools.TOOLS,
                thinking={"type": "adaptive"},
                messages=self.messages,
            )

            # Append the *whole* content list, not just the text. It contains
            # the tool_use blocks, and the next request will be rejected if
            # they're missing — every tool_result has to answer a tool_use the
            # model can still see. Same reason store.py keeps blocks as JSON.
            self._record("assistant", response.content)

            if response.stop_reason != "tool_use":
                return _text_of(response.content)

            # It asked for one or more tools. Run them all, then send every
            # result back in a single user message — splitting them across
            # several messages trains the model out of asking in parallel.
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                output, is_error = tools.dispatch(
                    block.name,
                    block.input,
                    store=self.store,
                    conversation_id=self.conversation_id,
                )
                print(f"  [{block.name} {block.input}]")
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,  # must match the request
                        "content": output,
                        "is_error": is_error,
                    }
                )

            self._record("user", results)

        return "(gave up after too many tool calls — something's looping)"

    def _record(self, role: str, content) -> None:
        """Append to the in-memory transcript and to disk, together.

        Kept as one call so the two can't drift. If you write to the list in
        one place and the database in another, you eventually find a path that
        does one and not the other, and reloading gives you a broken
        conversation the API refuses.
        """
        self.messages.append({"role": role, "content": content})
        self.store.append_message(self.conversation_id, role, content)


def _text_of(content) -> str:
    """Pull the readable text out of a response.

    A response is a list of blocks, and only some are text — there may be
    thinking blocks and tool_use blocks in there too. Reaching straight for
    content[0].text works right up until it doesn't.
    """
    return "\n".join(b.text for b in content if b.type == "text")
