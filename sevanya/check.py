"""Is the local model set up, and can it actually use her tools?

    python -m sevanya.check

Everything she does well runs through tool calls — reading your code, grepping
it, recall, her list. A model that chats beautifully and calls tools badly will
feel like *she* got worse rather than like the model did, so this asks the
question directly instead of leaving you to infer it from a bad afternoon.
"""

import json
import sys

import httpx

from . import backends, tools
from .prompt import SYSTEM

# One tool, described the way hers are. Deliberately a question that can only
# be answered by calling it: a model that just talks about reading the file has
# failed the thing we're testing.
PROBE = [t for t in tools.TOOLS if t["name"] == "read_file"]
ASK = "What does README.md say? Read it."

# Roughly, and it doesn't need to be better than roughly: the point is whether
# the context window is in the right order of magnitude.
def _tokens(text: str) -> int:
    return round(len(text) / 4)


def report(backend: backends.LocalBackend) -> int:
    print(f"backend:  {backend.describe()}")
    print(f"url:      {backend.url}")

    # --- is anything there? -------------------------------------------------
    try:
        response = httpx.get(f"{backend.url}/models", timeout=10)
        response.raise_for_status()
        listed = [m.get("id") for m in response.json().get("data", [])]
    except Exception as exc:
        print(f"\ncannot reach it ({type(exc).__name__}: {exc})")
        print("\n  - is the server started?  LM Studio: Developer tab -> Start Server")
        print("  - is the port right?      SEVANYA_LOCAL_URL is what she'll use")
        return 2

    print(f"loaded:   {', '.join(listed) if listed else '(nothing loaded)'}")
    if backend.model not in listed and listed:
        print(f"\n  note: SEVANYA_LOCAL_MODEL is {backend.model!r}, which isn't in that list.")
        print(f"        Most servers serve whatever is loaded anyway, but setting it to")
        print(f"        {listed[0]!r} removes the doubt.")

    # --- how much room does she need? ---------------------------------------
    overhead = _tokens(SYSTEM) + _tokens(json.dumps(backends.tools_for_openai(tools.TOOLS)))
    print(f"\nher fixed overhead: ~{overhead} tokens before you type anything")
    print(f"  ({len(tools.TOOLS)} tool definitions plus the teaching prompt)")
    print("  one read_file can add ~10,000 more, so set the model's context to")
    print("  16k at the very least — 32k if the card will take it.")

    # --- the question that matters ------------------------------------------
    print(f"\nasking it to use a tool: {ASK!r}")
    try:
        reply = backend.send(SYSTEM, [{"role": "user", "content": ASK}], PROBE)
    except Exception as exc:
        print(f"  the request failed ({type(exc).__name__}: {exc})")
        return 2

    calls = [b for b in reply.content if b.get("type") == "tool_use"]
    said = reply.text().strip()

    if calls:
        call = calls[0]
        print(f"  it called {call['name']}({json.dumps(call.get('input', {}))})")
        if call["name"] != "read_file":
            print("  ...but not the tool it was asked for. Workable, not promising.")
            return 1
        if "__malformed__" in call.get("input", {}):
            print("  ...with arguments that aren't valid JSON. She'll hand it back as an")
            print("  error and it may recover, but expect this to happen often.")
            return 1
        print("\n  good — this model calls tools. That's the thing that decides")
        print("  whether she works well on it.")
        return 0

    print(f"  it answered with words instead: {said[:120]!r}")
    print("\n  this model did not call the tool. She will be much worse on it —")
    print("  she can't read your code, grep it, or recall anything. Look for a")
    print("  model whose card mentions function calling or tool use, and check")
    print("  that tool use is enabled in the server settings.")
    return 1


def main(argv: list[str] | None = None) -> int:
    backend = backends.choose("local")
    return report(backend)


if __name__ == "__main__":
    raise SystemExit(main())
