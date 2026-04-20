"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

Unit tests for ToolClient (no real FIFOs created).
"""

import threading
from unittest.mock import MagicMock, patch

from named_pipes import text_named_pipe
from named_pipes.tool_client import ToolClient


def make_client(name="chat"):
    """Return a ToolClient with all filesystem calls patched out."""
    with (
        patch.object(text_named_pipe, "ensure_pipe"),
        patch.object(text_named_pipe, "remove_pipe"),
        patch.object(text_named_pipe.os, "pipe", return_value=(-1, -1)),
        patch.object(text_named_pipe.os, "open", return_value=3),
        patch.object(text_named_pipe.os, "fdopen", return_value=MagicMock()),
    ):
        client = ToolClient(name)
    return client


class TestPipePath:
    def test_pipe_name_derived_from_tool_name(self):
        client = make_client("stt")
        assert client._pipe_name == "/tmp/tool-stt"


class TestOnDecorator:
    def test_registers_handler(self):
        client = make_client()

        @client.on("reply")
        def _(msg):
            pass

        assert "reply" in client._handlers

    def test_returns_original_function(self):
        client = make_client()

        def handler(msg):
            pass

        result = client.on("reply")(handler)
        assert result is handler


class TestMsgHandlerFn:
    def test_subscribed_event_sets_flag(self):
        client = make_client()
        client._subscribed = MagicMock(spec=threading.Event)

        client.msg_handler_fn({"event": "subscribed"}, None)

        client._subscribed.set.assert_called_once()

    def test_subscribed_event_not_forwarded_to_handlers(self):
        client = make_client()
        mock_handler = MagicMock()
        client._handlers["subscribed"] = mock_handler

        client.msg_handler_fn({"event": "subscribed"}, None)

        mock_handler.assert_not_called()

    def test_registered_handler_called_with_msg(self):
        client = make_client()
        mock_handler = MagicMock()
        client._handlers["reply"] = mock_handler

        msg = {"event": "reply", "text": "hello"}
        client.msg_handler_fn(msg, None)

        mock_handler.assert_called_once_with(msg)

    def test_unknown_event_silently_ignored(self):
        client = make_client()
        client.msg_handler_fn({"event": "unknown_event"}, None)

    def test_missing_event_key_silently_ignored(self):
        client = make_client()
        client.msg_handler_fn({}, None)
