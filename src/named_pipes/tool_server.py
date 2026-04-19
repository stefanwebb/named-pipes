"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

ToolServer — implements the Named Pipe Tools protocol (server side).

See named-pipe-tools.md for the full specification.
"""

import inspect
import json
import os
from enum import Enum
from pathlib import Path

from named_pipes.text_named_pipe import TextNamedPipe, Role
from named_pipes.utils import scan_pipes


class ToolState(Enum):
    RUNNING = "running"
    STOPPING = "stopping"


class ToolServer(TextNamedPipe):
    """Named-pipe server that follows the Named Pipe Tools protocol.

    Listens on ``/tmp/tool-{name}`` for JSON commands from clients.
    Automatically handles ``subscribe``, ``unsubscribe``, ``description``,
    ``help``, and ``stop``.  Custom commands are registered with the
    ``@server.handler("CMD")`` decorator.
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
            # Look for SKILL.md next to the concrete subclass's module file.
            subclass_file = inspect.getfile(type(self))
            skill_md = Path(subclass_file).parent / "SKILL.md"
            help_text = skill_md.read_text() if skill_md.exists() else description
        self._help_text = help_text
        self._handlers: dict[str, callable] = {}
        self._register_builtin_handlers()
        self.set_state(ToolState.RUNNING)

        # On startup, remove orphaned tool pipes left by crashed servers/clients.
        # Only the server owns pipes in the directory; clients create their own
        # downstream pipe via TextNamedPipe and clean it up themselves.
        if role is Role.SERVER:
            folder = str(Path(pipe_name).parent)
            tool_prefix = os.path.join(folder, "tool-")
            result = scan_pipes(folder)
            for orphan in result["orphaned"]:
                if orphan.startswith(tool_prefix) and orphan != pipe_name:
                    try:
                        os.remove(orphan)
                    except OSError:
                        pass

    # --- state management ---

    def set_state(self, state: ToolState):
        self._state = state
        self.broadcast_message(
            json.dumps({"event": "state_changed", "state": state.value})
        )

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

    # --- built-in handlers ---

    def _register_builtin_handlers(self):
        @self.handler("subscribe")
        def _subscribe(msg, pid):
            self.subscribe(pid)
            self.send_response("subscribed", pid)

        @self.handler("unsubscribe")
        def _unsubscribe(msg, pid):
            self.unsubscribe(pid)  # No response per protocol spec

        @self.handler("description")
        def _description(msg, pid):
            self.send_response(self._description, pid)

        @self.handler("help")
        def _help(msg, pid):
            self.send_response(self._help_text, pid)

        @self.handler("ping")
        def _ping(msg, pid):
            self.send_response("pong", pid)

        @self.handler("status")
        def _status(msg, pid):
            self.send_response(self._state.value, pid)

        @self.handler("stop")
        def _stop(msg, pid):
            self.set_state(ToolState.STOPPING)
            self.broadcast_message(json.dumps({"result": "stopping"}))
            self.stop()

    # --- protocol message handler ---

    def msg_handler_fn(self, msg: dict, pid: int | None):
        cmd = msg.get("cmd", "").lower()
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
