"""Naming a conversation from what you said, not truncating it.

The one thing that has to hold regardless of what the model does: a broken
or slow title generator is never the reason a conversation fails to start.
"""

import json

import httpx

from sevanya import backends, titling


def server(reply_text=None, status=200):
    def handler(request):
        if reply_text is None:
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(status, json={
            "choices": [{"message": {"content": reply_text}, "finish_reason": "stop"}],
        })
    return handler


def backend(handler):
    return backends.LocalBackend(url="http://x/v1", model="m",
                                 client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_uses_the_models_title():
    title = titling.generate("why is my parser segfaulting?", backend=backend(server("Parser segfault debugging")))
    assert title == "Parser segfault debugging"


def test_strips_surrounding_quotes_the_model_added_anyway():
    title = titling.generate("hello", backend=backend(server('"Parser segfault debugging"')))
    assert title == "Parser segfault debugging"


def test_falls_back_to_the_raw_message_if_the_backend_errors():
    """Never raises -- a broken title generator isn't a reason a conversation can't start."""
    title = titling.generate("why is my parser segfaulting, exactly?", backend=backend(server(None)))
    assert title == "why is my parser segfaulting, exactly?"


def test_falls_back_if_the_model_returns_nothing():
    title = titling.generate("hello there", backend=backend(server("")))
    assert title == "hello there"


def test_title_is_truncated_even_if_the_model_ignores_the_length_instruction():
    long_reply = "a " * 100
    title = titling.generate("hi", backend=backend(server(long_reply)))
    assert len(title) <= titling.MAX_TITLE


def test_fallback_is_also_truncated():
    long_message = "why " * 40
    title = titling.generate(long_message, backend=backend(server(None)))
    assert len(title) <= titling.MAX_TITLE
    assert title == long_message[:titling.MAX_TITLE]
