"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

ToolClient — implements the client side of the Named Pipe Tools protocol.

See named-pipe-tools.md for the full specification.
"""

import json
import threading

from named_pipes.text_named_pipe import TextNamedPipe, Role


class ToolClient(TextNamedPipe):
    """Named-pipe client that follows the Named Pipe Tools protocol.

    Connects to a ``ToolServer`` at ``/tmp/tool-{name}``.

    The context manager starts the listener, subscribes on entry, and
    unsubscribes on exit::

        with ToolClient("chat") as client:
            client.send_command("ping")

    Without the context manager, call ``listen()`` then ``subscribe()``
    manually, and ``unsubscribe()`` / ``_close()`` before discarding.

    Override ``on_message(msg)`` to handle server responses.
    """

    def __init__(self, name: str):
        super().__init__(f"/tmp/tool-{name}", Role.CLIENT)
        self._subscribed = threading.Event()

    # --- sending helpers ---

    def send_command(self, cmd: str, **kwargs):
        """Send ``{"pid": ..., "cmd": cmd, ...kwargs}`` to the server."""
        payload = {"pid": self._pid, "cmd": cmd}
        payload.update(kwargs)
        self.send_message(json.dumps(payload))

    def subscribe(self):
        """Send ``subscribe`` and block until the server confirms."""
        self.send_command("subscribe")
        self._subscribed.wait()

    def unsubscribe(self):
        """Send ``unsubscribe`` (no response expected)."""
        self.send_command("unsubscribe")

    # --- message handler ---

    def msg_handler_fn(self, msg: dict, pid: int | None):
        if msg.get("event") == "subscribed":
            self._subscribed.set()
            return
        self.on_message(msg)

    def on_message(self, msg: dict):
        """Called for every server message after subscription is confirmed.

        Override in subclasses to handle tool-specific responses.
        """
        pass

    # --- context manager ---

    def __enter__(self):
        self.listen()
        self.subscribe()
        return self

    def __exit__(self, *_):
        self.unsubscribe()
        self._close()
