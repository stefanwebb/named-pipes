"""Unit tests for pipe_reader.PipeChannel (no real FIFOs created)."""
import sys
import os
from unittest.mock import MagicMock, patch, call

import pytest

# Ensure repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pipe_reader


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_channel():
    """Return a PipeChannel with all filesystem calls patched out."""
    with (
        patch.object(pipe_reader, "ensure_pipe"),
        patch.object(pipe_reader.os, "open", return_value=3),
        patch.object(pipe_reader.os, "fdopen", return_value=MagicMock()),
    ):
        ch = pipe_reader.PipeChannel("/tmp/test-pipe")
    return ch


# ---------------------------------------------------------------------------
# TestHandlerDecorator
# ---------------------------------------------------------------------------

class TestHandlerDecorator:
    def test_registers_handler(self):
        ch = make_channel()

        @ch.handler("ECHO")
        def on_echo(data):
            pass

        assert "ECHO" in ch._handlers

    def test_registers_multiple_handlers(self):
        ch = make_channel()

        @ch.handler("FOO")
        def on_foo(data):
            pass

        @ch.handler("BAR")
        def on_bar(data):
            pass

        assert "FOO" in ch._handlers
        assert "BAR" in ch._handlers

    def test_returns_original_function(self):
        ch = make_channel()

        def on_ping(data):
            return "pong"

        result = ch.handler("PING")(on_ping)
        assert result is on_ping


# ---------------------------------------------------------------------------
# TestDispatch
# ---------------------------------------------------------------------------

class TestDispatch:
    def test_calls_registered_handler(self):
        ch = make_channel()
        mock_handler = MagicMock()
        ch._handlers["ECHO"] = mock_handler

        ch.dispatch({"cmd": "ECHO", "data": "hello"})

        mock_handler.assert_called_once_with("hello")

    def test_dispatch_case_insensitive(self):
        ch = make_channel()
        mock_handler = MagicMock()
        ch._handlers["PING"] = mock_handler

        ch.dispatch({"cmd": "ping", "data": ""})

        mock_handler.assert_called_once_with("")

    def test_dispatch_unknown_sends_error(self):
        ch = make_channel()
        ch.send_message = MagicMock()

        ch.dispatch({"cmd": "UNKNOWN", "data": ""})

        ch.send_message.assert_called_once_with("ERROR", "unknown command 'UNKNOWN'")

    def test_dispatch_missing_data_defaults_to_empty(self):
        ch = make_channel()
        mock_handler = MagicMock()
        ch._handlers["PING"] = mock_handler

        ch.dispatch({"cmd": "PING"})

        mock_handler.assert_called_once_with("")
