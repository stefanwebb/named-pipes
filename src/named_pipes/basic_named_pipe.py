"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

import json
import threading

from named_pipes.data_named_pipe import DataNamedPipe
from named_pipes.text_named_pipe import TextNamedPipe
from named_pipes.text_named_pipe import Role


class BasicPipeChannel(TextNamedPipe, DataNamedPipe):
    """Concrete PipeChannel with decorator-based handler registration.

    Use ``@ch.handler("<CMD>")`` to register a function for a named command
    and ``@ch.data_handler`` to register a function for incoming data payloads.

    Registered command handlers must accept ``(msg: dict, pid: int | None)``.
    The data handler must accept ``(data: bytes, pid: int | None)``.
    """

    def __init__(self, pipe_name: str = "/tmp/basic_pipe", role: Role = Role.SERVER):
        TextNamedPipe.__init__(self, pipe_name, role)
        DataNamedPipe.__init__(self, pipe_name + "_data", role)
        self._handlers: dict[str, callable] = {}
        self._data_handler_fn_impl: callable | None = None

    def handler(self, cmd: str):
        """Decorator that registers a function as the handler for `cmd`."""

        def decorator(fn):
            self._handlers[cmd.upper()] = fn
            return fn

        return decorator

    def data_handler(self, fn):
        """Decorator that registers a function as the handler for incoming data payloads."""
        self._data_handler_fn_impl = fn
        return fn

    def subscribe(self, pid: int):
        TextNamedPipe.subscribe(self, pid)
        DataNamedPipe.subscribe(self, pid)

    def unsubscribe(self, pid: int):
        TextNamedPipe.unsubscribe(self, pid)
        DataNamedPipe.unsubscribe(self, pid)

    def send_message(self, cmd: str, data: str = "", pid: int | None = None):
        msg = {"cmd": cmd, "data": data, "pid": self._pid}
        TextNamedPipe.send_message(self, json.dumps(msg), pid)

    def msg_handler_fn(self, msg: dict, pid: int | None):
        if msg["cmd"].upper() == "QUIT":
            self.send_message("BYE", pid=pid)
            print("Quit received. Shutting down.")
            self.stop()
        else:
            self.dispatch(msg, pid)

    def data_handler_fn(self, data: bytes, pid: int | None):
        if self._data_handler_fn_impl is not None:
            self._data_handler_fn_impl(data, pid)

    def dispatch(self, msg: dict, pid: int | None):
        cmd = msg["cmd"].upper()
        fn = self._handlers.get(cmd)
        if fn:
            fn(msg, pid)
        else:
            self.send_message("ERROR", f"unknown command '{cmd}'", pid=pid)

    def stop(self):
        TextNamedPipe.stop(self)
        DataNamedPipe.stop_data(self)

    def listen(self) -> threading.Event:
        """Start background threads for both text and data pipes.

        Returns a threading.Event that is set when both listener threads have exited.
        """
        text_done = TextNamedPipe.listen(self)
        data_done = DataNamedPipe.listen_data(self)

        done = threading.Event()

        def _wait_both():
            text_done.wait()
            data_done.wait()
            done.set()

        threading.Thread(target=_wait_both, daemon=True).start()
        return done

    def _close(self):
        TextNamedPipe._close(self)
        DataNamedPipe._close_data(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._close()
