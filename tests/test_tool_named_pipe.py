"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

Unit tests for tool_named_pipe.ToolServer (no real FIFOs created).
"""

import json
from unittest.mock import MagicMock, patch

from named_pipes import text_named_pipe
from named_pipes.tool_server import ToolServer


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_tool(**kwargs):
    """Return a ToolServer with all filesystem calls patched out."""
    defaults = {"description": "A test tool", "help_text": "Test help text"}
    defaults.update(kwargs)
    with (
        patch.object(text_named_pipe, "ensure_pipe"),
        patch.object(text_named_pipe.os, "pipe", return_value=(-1, -1)),
        patch.object(text_named_pipe.os, "open", return_value=3),
        patch.object(text_named_pipe.os, "fdopen", return_value=MagicMock()),
        patch(
            "named_pipes.tool_server.scan_pipes",
            return_value={"connected": [], "orphaned": []},
        ),
    ):
        tool = ToolServer("test-tool", **defaults)
    return tool


# ---------------------------------------------------------------------------
# TestPipePath
# ---------------------------------------------------------------------------


class TestPipePath:
    def test_pipe_name_derived_from_tool_name(self):
        tool = make_tool()
        assert tool._pipe_name == "/tmp/tool-test-tool"


# ---------------------------------------------------------------------------
# TestHandlerDecorator
# ---------------------------------------------------------------------------


class TestHandlerDecorator:
    def test_registers_handler_lowercase(self):
        tool = make_tool()

        @tool.handler("echo")
        def on_echo(msg, pid):
            pass

        assert "echo" in tool._handlers

    def test_returns_original_function(self):
        tool = make_tool()

        def on_echo(msg, pid):
            pass

        result = tool.handler("echo")(on_echo)
        assert result is on_echo


# ---------------------------------------------------------------------------
# TestProtocolCommands
# ---------------------------------------------------------------------------


class TestProtocolCommands:
    def test_subscribe(self):
        tool = make_tool()
        tool.subscribe = MagicMock()
        tool.send_event = MagicMock()

        tool.msg_handler_fn({"cmd": "subscribe", "pid": 1234}, 1234)

        tool.subscribe.assert_called_once_with(1234)
        tool.send_event.assert_called_once_with("subscribed", 1234)

    def test_unsubscribe(self):
        tool = make_tool()
        tool.unsubscribe = MagicMock()

        tool.msg_handler_fn({"cmd": "unsubscribe", "pid": 1234}, 1234)

        tool.unsubscribe.assert_called_once_with(1234)

    def test_description(self):
        tool = make_tool(description="My cool tool")
        tool.send_event = MagicMock()

        tool.msg_handler_fn({"cmd": "get_description", "pid": 1}, 1)

        tool.send_event.assert_called_once_with(
            "description", 1, description="My cool tool"
        )

    def test_help(self):
        tool = make_tool(help_text="Use me like this")
        tool.send_event = MagicMock()

        tool.msg_handler_fn({"cmd": "get_help", "pid": 1}, 1)

        tool.send_event.assert_called_once_with("help", 1, help="Use me like this")

    def test_stop(self):
        tool = make_tool()
        tool.broadcast_message = MagicMock()
        tool.stop = MagicMock()

        tool.msg_handler_fn({"cmd": "stop", "pid": 1}, 1)

        tool.broadcast_message.assert_any_call(
            json.dumps({"event": "state_changed", "state": "stopping"})
        )
        tool.stop.assert_called_once()

    def test_unknown_command(self):
        tool = make_tool()
        tool.send_event = MagicMock()

        tool.msg_handler_fn({"cmd": "nosuch", "pid": 1}, 1)

        tool.send_event.assert_called_once_with(
            "error", 1, message="unknown command 'nosuch'"
        )


# ---------------------------------------------------------------------------
# TestCustomDispatch
# ---------------------------------------------------------------------------


class TestCustomDispatch:
    def test_custom_handler_called_with_msg_and_pid(self):
        tool = make_tool()
        mock_handler = MagicMock()
        tool._handlers["echo"] = mock_handler

        msg = {"cmd": "echo", "pid": 1, "text": "hello"}
        tool.msg_handler_fn(msg, 1)

        mock_handler.assert_called_once_with(msg, 1)


# ---------------------------------------------------------------------------
# TestSendHelpers
# ---------------------------------------------------------------------------


class TestSendHelpers:
    def test_send_event_targeted(self):
        tool = make_tool()
        tool.send_message = MagicMock()

        tool.send_event("pong", 42)

        tool.send_message.assert_called_once_with(json.dumps({"event": "pong"}), 42)

    def test_send_event_with_kwargs(self):
        tool = make_tool()
        tool.send_message = MagicMock()

        tool.send_event("state", 42, state="running")

        tool.send_message.assert_called_once_with(
            json.dumps({"event": "state", "state": "running"}), 42
        )

    def test_send_event_broadcast(self):
        tool = make_tool()
        tool.send_message = MagicMock()

        tool.send_event("pong")

        tool.send_message.assert_called_once_with(json.dumps({"event": "pong"}), None)
