"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

"""ToolNamedPipe — implements the Named Pipe Tools protocol.

See named-pipe-tools.md for the full specification.
"""

import json

from named_pipes.text_named_pipe import TextNamedPipe, Role


class ToolNamedPipe(TextNamedPipe):
    """A named-pipe tool that follows the Named Pipe Tools protocol.

    Server (tool) side:
        Listens on ``/tmp/tool-{name}`` for JSON commands from clients.
        Automatically handles ``subscribe``, ``unsubscribe``, ``description``,
        ``help``, and ``exit``.  Custom commands are registered with the
        ``@tool.handler("CMD")`` decorator.

    Client side:
        Creates its downstream pipe at ``/tmp/tool-{name}-{pid}`` and provides
        ``send_command`` / ``send_response`` helpers.
    """

    def __init__(
        self,
        name: str,
        role: Role = Role.SERVER,
        *,
        description: str = "",
        help_text: str = "",
    ):
        pipe_name = f"/tmp/tool-{name}"
        super().__init__(pipe_name, role)
        self._tool_name = name
        self._description = description
        self._help_text = help_text
        self._handlers: dict[str, callable] = {}

    # --- decorator for custom commands ---

    def handler(self, cmd: str):
        """Decorator that registers a function as the handler for *cmd*."""

        def decorator(fn):
            self._handlers[cmd.lower()] = fn
            return fn

        return decorator

    # --- sending helpers ---

    def send_response(self, result: str):
        """Broadcast ``{"result": ...}`` to all subscribers (server) or send upstream (client)."""
        self.send_message(json.dumps({"result": result}))

    def send_command(self, cmd: str):
        """Send ``{"pid": ..., "cmd": ...}`` upstream (client only)."""
        self.send_message(json.dumps({"pid": self._pid, "cmd": cmd}))

    # --- protocol message handler ---

    def msg_handler_fn(self, msg: dict):
        cmd = msg.get("cmd", "").lower()
        pid = msg.get("pid")

        match cmd:
            case "subscribe":
                self.subscribe(pid)
                self.send_response("subscribed")

            case "unsubscribe":
                self.unsubscribe(pid)
                # No response per protocol spec

            case "description":
                self.send_response(self._description)

            case "help":
                self.send_response(self._help_text)

            case "exit":
                self.send_response("exiting")
                self.stop()

            case _:
                self._dispatch(cmd, msg)

    def _dispatch(self, cmd: str, msg: dict):
        fn = self._handlers.get(cmd)
        if fn:
            fn(msg)
        else:
            self.send_response(f"unknown command '{cmd}'")

    # --- context manager ---

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._close()
