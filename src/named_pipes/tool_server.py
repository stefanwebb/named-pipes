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
    Automatically handles ``subscribe``, ``unsubscribe``, ``ping``,
    ``get_state``, ``get_description``, ``get_help``, ``get_config``,
    and ``stop``.  Custom commands are registered with the
    ``@server.handler("CMD")`` decorator.
    """

    def __init__(
        self,
        name: str,
        *,
        description: str,
        help_text: str | None = None,
    ):
        pipe_name = f"/tmp/tool-{name}"
        super().__init__(pipe_name, Role.SERVER)
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

    def send_event(self, event: str, pid: int | None = None, **kwargs):
        """Send ``{"event": event, ...kwargs}`` to *pid* (or broadcast if *pid* is None)."""
        payload = {"event": event}
        payload.update(kwargs)
        self.send_message(json.dumps(payload), pid)

    # --- config hook for subclasses ---

    def _get_config(self) -> dict:
        return {}

    def _list_interfaces(self) -> list[str]:
        return ["base"]

    # --- built-in handlers ---

    def _register_builtin_handlers(self):
        @self.handler("subscribe")
        def _subscribe(msg, pid):
            self.subscribe(pid)
            self.send_event("subscribed", pid)

        @self.handler("unsubscribe")
        def _unsubscribe(msg, pid):
            self.unsubscribe(pid)  # No response per protocol spec

        @self.handler("get_description")
        def _get_description(msg, pid):
            self.send_event("description", pid, description=self._description)

        @self.handler("get_help")
        def _get_help(msg, pid):
            self.send_event("help", pid, help=self._help_text)

        @self.handler("ping")
        def _ping(msg, pid):
            self.send_event("pong", pid)

        @self.handler("get_state")
        def _get_state(msg, pid):
            self.send_event("state", pid, state=self._state.value)

        @self.handler("get_config")
        def _handle_get_config(msg, pid):
            self.send_event("config", pid, **self._get_config())

        @self.handler("list_interfaces")
        def _list_interfaces(msg, pid):
            self.send_event("interfaces", pid, interfaces=self._list_interfaces())

        @self.handler("stop")
        def _stop(msg, pid):
            self.set_state(ToolState.STOPPING)
            self.stop()

    # --- protocol message handler ---

    def msg_handler_fn(self, msg: dict, pid: int | None):
        cmd = msg.get("cmd", "").lower()
        fn = self._handlers.get(cmd)
        if fn:
            fn(msg, pid)
        else:
            self.send_event("error", pid, message=f"unknown command '{cmd}'")

    # --- context manager ---

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._close()
