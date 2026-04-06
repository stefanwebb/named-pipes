"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

Unit tests for tool_named_pipe.ToolNamedPipe (no real FIFOs created).
"""

import json
from unittest.mock import MagicMock, patch

from named_pipes import text_named_pipe
from named_pipes.tool_named_pipe import ToolNamedPipe


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_tool(**kwargs):
    """Return a ToolNamedPipe with all filesystem calls patched out."""
    defaults = {"description": "A test tool", "help_text": "Test help text"}
    defaults.update(kwargs)
    with (
        patch.object(text_named_pipe, "ensure_pipe"),
        patch.object(text_named_pipe.os, "pipe", return_value=(10, 11)),
        patch.object(text_named_pipe.os, "open", return_value=3),
        patch.object(text_named_pipe.os, "fdopen", return_value=MagicMock()),
    ):
        tool = ToolNamedPipe("test-tool", **defaults)
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
        tool.send_response = MagicMock()

        tool.msg_handler_fn({"cmd": "subscribe", "pid": 1234}, 1234)

        tool.subscribe.assert_called_once_with(1234)
        tool.send_response.assert_called_once_with("subscribed", 1234)

    def test_unsubscribe(self):
        tool = make_tool()
        tool.unsubscribe = MagicMock()

        tool.msg_handler_fn({"cmd": "unsubscribe", "pid": 1234}, 1234)

        tool.unsubscribe.assert_called_once_with(1234)

    def test_description(self):
        tool = make_tool(description="My cool tool")
        tool.send_response = MagicMock()

        tool.msg_handler_fn({"cmd": "description", "pid": 1}, 1)

        tool.send_response.assert_called_once_with("My cool tool", 1)

    def test_help(self):
        tool = make_tool(help_text="Use me like this")
        tool.send_response = MagicMock()

        tool.msg_handler_fn({"cmd": "help", "pid": 1}, 1)

        tool.send_response.assert_called_once_with("Use me like this", 1)

    def test_exit(self):
        tool = make_tool()
        tool.broadcast_message = MagicMock()
        tool.stop = MagicMock()

        tool.msg_handler_fn({"cmd": "exit", "pid": 1}, 1)

        tool.broadcast_message.assert_called_once_with(
            json.dumps({"result": "exiting"})
        )
        tool.stop.assert_called_once()

    def test_unknown_command(self):
        tool = make_tool()
        tool.send_response = MagicMock()

        tool.msg_handler_fn({"cmd": "nosuch", "pid": 1}, 1)

        tool.send_response.assert_called_once_with("unknown command 'nosuch'", 1)


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
    def test_send_response_targeted(self):
        tool = make_tool()
        tool.send_message = MagicMock()

        tool.send_response("ok", 42)

        tool.send_message.assert_called_once_with(json.dumps({"result": "ok"}), 42)

    def test_send_response_broadcast(self):
        tool = make_tool()
        tool.send_message = MagicMock()

        tool.send_response("ok")

        tool.send_message.assert_called_once_with(json.dumps({"result": "ok"}), None)

    def test_send_command(self):
        tool = make_tool()
        tool.send_message = MagicMock()
        tool._pid = 42

        tool.send_command("ping")

        tool.send_message.assert_called_once_with(
            json.dumps({"pid": 42, "cmd": "ping"})
        )
