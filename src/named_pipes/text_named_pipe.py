"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

import json
import os
import select
import threading
from abc import ABC, abstractmethod
from enum import Enum

from named_pipes.utils import ensure_pipe, remove_pipe


class Role(Enum):
    SERVER = "server"
    CLIENT = "client"


class TextNamedPipe(ABC):
    """Base class for text/message named-pipe IPC.

    Servers open a single upstream pipe for receiving and use subscribe()
    to add downstream pipes (keyed by pid) for broadcasting replies.

    Clients open a single downstream pipe for receiving.

    Pipe paths:
        <pipe_name>                           client -> server  (one, shared)
        <pipe_name>-<pid>                     server -> client  (one per subscriber)
    """

    def __init__(
        self,
        pipe_name: str = "/tmp/pipe",
        role: Role = Role.SERVER,
        pid: int | None = None,
    ):
        self._role = role
        self._pid = pid if pid is not None else os.getpid()
        self._text_stop_r, self._text_stop_w = os.pipe()
        self._text_listener_thread: threading.Thread | None = None

        self._closed = False
        self._pipe_name = pipe_name
        if role is Role.SERVER:
            ensure_pipe(pipe_name)
            self._msg_recv = os.fdopen(os.open(pipe_name, os.O_RDWR), "r", buffering=1)
            self._owned_pipes = [pipe_name]
            self._subscribers: dict[int, tuple[str, object]] = {}
        else:
            downstream = f"{pipe_name}-{self._pid}"
            ensure_pipe(downstream)
            self._msg_recv = os.fdopen(os.open(downstream, os.O_RDWR), "r", buffering=1)
            self._msg_send = os.fdopen(os.open(pipe_name, os.O_RDWR), "w", buffering=1)
            self._owned_pipes = [downstream]

    # --- subscribe / unsubscribe (server only) ---

    def subscribe(self, pid: int, filepath: str | None = None):
        """Add a downstream pipe for *pid*.  Opens ``<filepath>-<pid>``."""
        if self._role is not Role.SERVER:
            raise RuntimeError("subscribe is only available on servers")
        path = f"{filepath or self._pipe_name}-{pid}"
        ensure_pipe(path)
        f = os.fdopen(os.open(path, os.O_RDWR), "w", buffering=1)
        self._subscribers[pid] = (path, f)

    def unsubscribe(self, pid: int):
        """Close the downstream pipe for *pid* on the server side."""
        if self._role is not Role.SERVER:
            raise RuntimeError("unsubscribe is only available on servers")
        _, f = self._subscribers.pop(pid)
        f.close()

    # --- message pipe ---

    def recv_message(self) -> dict:
        line = self._msg_recv.readline().rstrip("\n")
        return json.loads(line)

    def send_message(self, data: str, pid: int | None = None):
        """Send *data* to one subscriber (*pid* given) or all subscribers (*pid* = None).

        On the client side the *pid* parameter is ignored and the message is
        written to the upstream pipe.
        """
        if self._role is Role.SERVER:
            if pid is None:
                for _, f in self._subscribers.values():
                    f.write(data + "\n")
                    f.flush()
            else:
                subscriber = self._subscribers.get(pid)
                if subscriber is None:
                    return
                _, f = subscriber
                f.write(data + "\n")
                f.flush()
        else:
            self._msg_send.write(data + "\n")
            self._msg_send.flush()

    def broadcast_message(self, data: str):
        """Send *data* to all subscribers (server only convenience alias)."""
        self.send_message(data, pid=None)

    # --- abstract handler ---

    @abstractmethod
    def msg_handler_fn(self, msg: dict, pid: int | None):
        """Called for each incoming message.

        *pid* is the sender's process ID extracted from the message (server
        side) or ``None`` when receiving a server response on the client side.
        """

    # --- listen loop ---

    def stop(self):
        """Unblock the listen() loop."""
        os.write(self._text_stop_w, b"\x00")

    def listen(self) -> threading.Event:
        """Start a background thread that dispatches messages until stop().

        Returns a threading.Event that is set when the listener thread exits.
        """
        done = threading.Event()

        def _msg_loop():
            try:
                while True:
                    readable, _, _ = select.select(
                        [self._msg_recv, self._text_stop_r], [], []
                    )
                    if self._text_stop_r in readable:
                        break
                    msg = self.recv_message()
                    if not msg:
                        continue
                    pid = msg.get("pid")
                    self.msg_handler_fn(msg, pid)
            finally:
                done.set()

        self._text_listener_thread = threading.Thread(target=_msg_loop, daemon=True)
        self._text_listener_thread.start()
        return done

    def _close(self):
        if self._closed:
            return
        self._closed = True
        self.stop()
        if self._text_listener_thread is not None:
            self._text_listener_thread.join()
            self._text_listener_thread = None
        self._msg_recv.close()
        if self._role is Role.SERVER:
            for pid in list(self._subscribers):
                self.unsubscribe(pid)
        else:
            self._msg_send.close()
        for fd in (self._text_stop_r, self._text_stop_w):
            try:
                os.close(fd)
            except OSError:
                pass
        for path in self._owned_pipes:
            remove_pipe(path)

    def __del__(self):
        self._close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._close()
