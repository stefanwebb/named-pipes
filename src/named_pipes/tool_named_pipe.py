"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

ToolNamedPipe — implements the Named Pipe Tools protocol.

See named-pipe-tools.md for the full specification.
"""

import json
from pathlib import Path

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
        description: str,
        help_text: str | None = None,
    ):
        pipe_name = f"/tmp/tool-{name}"
        super().__init__(pipe_name, role)
        self._tool_name = name
        self._description = description
        if help_text is None:
            skill_md = Path.cwd() / "SKILL.md"
            help_text = skill_md.read_text() if skill_md.exists() else description
        self._help_text = help_text
        self._handlers: dict[str, callable] = {}

    # --- decorator for custom commands ---

    def handler(self, cmd: str):
        """Decorator that registers a function as the handler for *cmd*.

        The registered function must accept ``(msg: dict, pid: int | None)``.
        """

        def decorator(fn):
            self._handlers[cmd.lower()] = fn
            return fn

        return decorator

    # --- sending helpers ---

    def send_response(self, result: str, pid: int | None = None):
        """Send ``{"result": ...}`` to *pid* (or broadcast if *pid* is None)."""
        self.send_message(json.dumps({"result": result}), pid)

    def send_command(self, cmd: str):
        """Send ``{"pid": ..., "cmd": ...}`` upstream (client only)."""
        self.send_message(json.dumps({"pid": self._pid, "cmd": cmd}))

    # --- protocol message handler ---

    def msg_handler_fn(self, msg: dict, pid: int | None):
        cmd = msg.get("cmd", "").lower()

        match cmd:
            case "subscribe":
                self.subscribe(pid)
                self.send_response("subscribed", pid)

            case "unsubscribe":
                self.unsubscribe(pid)
                # No response per protocol spec

            case "description":
                self.send_response(self._description, pid)

            case "help":
                self.send_response(self._help_text, pid)

            case "exit":
                self.broadcast_message(json.dumps({"result": "exiting"}))
                self.stop()

            case _:
                self._dispatch(cmd, msg, pid)

    def _dispatch(self, cmd: str, msg: dict, pid: int | None):
        fn = self._handlers.get(cmd)
        if fn:
            fn(msg, pid)
        else:
            self.send_response(f"unknown command '{cmd}'", pid)

    # --- context manager ---

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._close()
