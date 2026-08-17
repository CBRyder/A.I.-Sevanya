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

MODEL = "claude-opus-5"

# A runaway loop is a runaway bill. If it's made this many tool calls without
# arriving at an answer, something is wrong and you want to know about it.
MAX_STEPS = 12


class Agent:
    def __init__(self, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic()
        # The conversation. The API is stateless — the model remembers nothing
        # between calls — so this list *is* Sevanya's memory of the session.
        # Everything it knows about what you two have discussed is in here,
        # and gets re-sent in full on every single turn.
        self.messages: list[dict] = []

    def send(self, user_text: str) -> str:
        """Send one user message, run any tools it triggers, return the reply."""
        self.messages.append({"role": "user", "content": user_text})

        for _ in range(MAX_STEPS):
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM,
                tools=tools.TOOLS,
                thinking={"type": "adaptive"},
                messages=self.messages,
            )

            # Append the *whole* content list, not just the text. It contains
            # the tool_use blocks, and the next request will be rejected if
            # they're missing — every tool_result has to answer a tool_use the
            # model can still see.
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                return _text_of(response.content)

            # It asked for one or more tools. Run them all, then send every
            # result back in a single user message — splitting them across
            # several messages trains the model out of asking in parallel.
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                output, is_error = tools.dispatch(block.name, block.input)
                print(f"  [{block.name} {block.input}]")
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,  # must match the request
                        "content": output,
                        "is_error": is_error,
                    }
                )

            self.messages.append({"role": "user", "content": results})

        return "(gave up after too many tool calls — something's looping)"


def _text_of(content) -> str:
    """Pull the readable text out of a response.

    A response is a list of blocks, and only some are text — there may be
    thinking blocks and tool_use blocks in there too. Reaching straight for
    content[0].text works right up until it doesn't.
    """
    return "\n".join(b.text for b in content if b.type == "text")
