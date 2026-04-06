"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

Unit tests for basic_named_pipe.BasicPipeChannel (no real FIFOs created).
"""

from unittest.mock import MagicMock, patch

from named_pipes import text_named_pipe, data_named_pipe
from named_pipes.basic_named_pipe import BasicPipeChannel


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_channel():
    """Return a BasicPipeChannel with all filesystem calls patched out."""
    with (
        patch.object(text_named_pipe, "ensure_pipe"),
        patch.object(data_named_pipe, "ensure_pipe"),
        patch.object(text_named_pipe.os, "pipe", return_value=(-1, -1)),
        patch.object(text_named_pipe.os, "open", return_value=3),
        patch.object(text_named_pipe.os, "fdopen", return_value=MagicMock()),
    ):
        ch = BasicPipeChannel("/tmp/test-pipe")
    return ch


# ---------------------------------------------------------------------------
# TestHandlerDecorator
# ---------------------------------------------------------------------------


class TestHandlerDecorator:
    def test_registers_handler(self):
        ch = make_channel()

        @ch.handler("ECHO")
        def on_echo(msg, pid):
            pass

        assert "ECHO" in ch._handlers

    def test_registers_multiple_handlers(self):
        ch = make_channel()

        @ch.handler("FOO")
        def on_foo(msg, pid):
            pass

        @ch.handler("BAR")
        def on_bar(msg, pid):
            pass

        assert "FOO" in ch._handlers
        assert "BAR" in ch._handlers

    def test_returns_original_function(self):
        ch = make_channel()

        def on_ping(msg, pid):
            return "pong"

        result = ch.handler("PING")(on_ping)
        assert result is on_ping


# ---------------------------------------------------------------------------
# TestDataHandlerDecorator
# ---------------------------------------------------------------------------


class TestDataHandlerDecorator:
    def test_registers_data_handler(self):
        ch = make_channel()

        @ch.data_handler
        def on_data(data, pid):
            pass

        assert ch._data_handler_fn_impl is on_data

    def test_data_handler_fn_calls_impl(self):
        ch = make_channel()
        mock_handler = MagicMock()
        ch._data_handler_fn_impl = mock_handler

        ch.data_handler_fn(b"hello", None)

        mock_handler.assert_called_once_with(b"hello", None)

    def test_data_handler_fn_with_pid(self):
        ch = make_channel()
        mock_handler = MagicMock()
        ch._data_handler_fn_impl = mock_handler

        ch.data_handler_fn(b"hello", 1234)

        mock_handler.assert_called_once_with(b"hello", 1234)

    def test_data_handler_fn_noop_when_no_impl(self):
        ch = make_channel()
        ch.data_handler_fn(b"hello", None)  # should not raise


# ---------------------------------------------------------------------------
# TestDispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_calls_registered_handler_with_msg_and_pid(self):
        ch = make_channel()
        mock_handler = MagicMock()
        ch._handlers["ECHO"] = mock_handler

        msg = {"cmd": "ECHO", "data": "hello"}
        ch.dispatch(msg, 42)

        mock_handler.assert_called_once_with(msg, 42)

    def test_dispatch_case_insensitive(self):
        ch = make_channel()
        mock_handler = MagicMock()
        ch._handlers["PING"] = mock_handler

        msg = {"cmd": "ping", "data": ""}
        ch.dispatch(msg, 99)

        mock_handler.assert_called_once_with(msg, 99)

    def test_dispatch_unknown_sends_error(self):
        ch = make_channel()
        ch.send_message = MagicMock()

        ch.dispatch({"cmd": "UNKNOWN", "data": ""}, None)

        ch.send_message.assert_called_once_with(
            "ERROR", "unknown command 'UNKNOWN'", pid=None
        )


# ---------------------------------------------------------------------------
# TestMsgHandlerFn
# ---------------------------------------------------------------------------


class TestMsgHandlerFn:
    def test_quit_sends_bye_and_stops(self):
        ch = make_channel()
        ch.send_message = MagicMock()
        ch.stop = MagicMock()

        ch.msg_handler_fn({"cmd": "QUIT", "data": ""}, None)

        ch.send_message.assert_called_once_with("BYE", pid=None)
        ch.stop.assert_called_once()

    def test_non_quit_dispatches_to_handler(self):
        ch = make_channel()
        mock_handler = MagicMock()
        ch._handlers["PING"] = mock_handler

        msg = {"cmd": "PING", "data": ""}
        ch.msg_handler_fn(msg, 77)

        mock_handler.assert_called_once_with(msg, 77)


# ---------------------------------------------------------------------------
# TestDataPipeSendData
# ---------------------------------------------------------------------------


class TestDataPipeSendData:
    def _make_server_data_pipe(self):
        """Return a DataNamedPipe in server role with filesystem calls patched."""
        from named_pipes import data_named_pipe
        from named_pipes.data_named_pipe import DataNamedPipe

        class _ConcreteData(DataNamedPipe):
            def data_handler_fn(self, data, pid):
                pass

        with (
            patch.object(data_named_pipe, "ensure_pipe"),
            patch.object(text_named_pipe.os, "pipe", return_value=(-1, -1)),
            patch.object(text_named_pipe.os, "open", return_value=4),
            patch.object(text_named_pipe.os, "fdopen", return_value=MagicMock()),
        ):
            pipe = _ConcreteData("/tmp/test-data-pipe")
        return pipe

    def test_targeted_send_writes_only_to_pid_subscriber(self):
        pipe = self._make_server_data_pipe()
        mock_f1 = MagicMock()
        mock_f2 = MagicMock()
        pipe._data_subscribers = {
            111: ("/tmp/test-data-pipe-111", mock_f1),
            222: ("/tmp/test-data-pipe-222", mock_f2),
        }

        pipe.send_data(b"hello", 111)

        mock_f1.write.assert_called()
        mock_f2.write.assert_not_called()

    def test_broadcast_writes_to_all_subscribers(self):
        pipe = self._make_server_data_pipe()
        mock_f1 = MagicMock()
        mock_f2 = MagicMock()
        pipe._data_subscribers = {
            111: ("/tmp/test-data-pipe-111", mock_f1),
            222: ("/tmp/test-data-pipe-222", mock_f2),
        }

        pipe.send_data(b"hello")  # pid=None → broadcast

        mock_f1.write.assert_called()
        mock_f2.write.assert_called()

    def test_send_to_unknown_pid_is_silently_ignored(self):
        pipe = self._make_server_data_pipe()
        pipe._data_subscribers = {}

        pipe.send_data(b"hello", 999)  # should not raise
