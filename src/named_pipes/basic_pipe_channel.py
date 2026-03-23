#!/usr/bin/env python3
import json

from named_pipes.abstract_pipe_channel import AbstractPipeChannel, Role


class BasicPipeChannel(AbstractPipeChannel):
    """Concrete PipeChannel with decorator-based handler registration.

    Use ``@ch.handler("<CMD>")`` to register a function for a named command
    and ``@ch.data_handler`` to register a function for incoming data payloads.
    """

    def __init__(self, pipe_name: str = "/tmp/agent", role: Role = Role.SERVER):
        super().__init__(pipe_name, role)
        self._handlers: dict[str, callable] = {}
        self._data_handler_fn: callable | None = None

    def handler(self, cmd: str):
        """Decorator that registers a function as the handler for `cmd`."""

        def decorator(fn):
            self._handlers[cmd] = fn
            return fn

        return decorator

    def data_handler(self, fn):
        """Decorator that registers a function as the handler for incoming data payloads."""
        self._data_handler_fn = fn
        return fn

    def send_message(self, cmd: str, data: str = ""):
        super().send_message(json.dumps({"cmd": cmd, "data": data}))

    def msg_handler_fn(self, msg: dict):
        if msg["cmd"].upper() == "QUIT":
            self.send_message("BYE")
            print("Quit received. Shutting down.")
            self.stop()
        else:
            self.dispatch(msg)

    def data_handler_fn(self, data: bytes):
        if self._data_handler_fn is not None:
            self._data_handler_fn(data)

    def dispatch(self, msg: dict):
        cmd = msg["cmd"].upper()
        data = msg.get("data", "")
        fn = self._handlers.get(cmd)
        if fn:
            fn(data)
        else:
            self.send_message("ERROR", f"unknown command '{cmd}'")
