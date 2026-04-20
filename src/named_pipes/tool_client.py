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

    Register event handlers with the ``on`` decorator::

        @client.on("reply")
        def _(msg):
            print(msg.get("text"))
    """

    def __init__(self, name: str):
        super().__init__(f"/tmp/tool-{name}", Role.CLIENT)
        self._subscribed = threading.Event()
        self._handlers: dict[str, callable] = {}

    # --- decorator for event handlers ---

    def on(self, event: str):
        """Decorator that registers a handler for *event*.

        The registered function must accept ``(msg: dict)``.
        """

        def decorator(fn):
            self._handlers[event] = fn
            return fn

        return decorator

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

    def msg_handler_fn(self, msg: dict, _pid: int | None):
        if msg.get("event") == "subscribed":
            self._subscribed.set()
            return
        fn = self._handlers.get(msg.get("event", ""))
        if fn:
            fn(msg)

    # --- context manager ---

    def __enter__(self):
        self.listen()
        self.subscribe()
        return self

    def __exit__(self, *_):
        self.unsubscribe()
        self._close()
