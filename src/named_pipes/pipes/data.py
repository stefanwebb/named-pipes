"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

import os
import select
import struct
import threading
from abc import ABC, abstractmethod

from named_pipes.pipes.text import Role
from named_pipes.utils import ensure_pipe, remove_pipe


class DataNamedPipe(ABC):
    """Base class for binary data named-pipe IPC.

    Upstream wire format (client → server):
        [4-byte PID big-endian][4-byte length big-endian][payload]

    Downstream wire format (server → client):
        [4-byte length big-endian][payload]  (unchanged)

    Servers open a single upstream pipe for receiving and use subscribe()
    to add downstream pipes (keyed by pid) for targeted or broadcast data.

    Clients open a downstream pipe for receiving and an upstream pipe for
    sending (with automatic PID prepending).

    Pipe paths:
        <pipe_name>                           client -> server  (one, shared)
        <pipe_name>-<pid>                     server -> client  (one per subscriber)
    """

    def __init__(
        self,
        pipe_name: str = "/tmp/pipe_data",
        role: Role = Role.SERVER,
        pid: int | None = None,
    ):
        self._data_role = role
        self._pid = pid if pid is not None else os.getpid()
        self._data_stop_r, self._data_stop_w = os.pipe()
        self._data_listener_thread: threading.Thread | None = None

        self._data_closed = False
        self._data_pipe_name = pipe_name
        if role is Role.SERVER:
            ensure_pipe(pipe_name)
            self._data_recv = os.fdopen(
                os.open(pipe_name, os.O_RDWR), "rb", buffering=0
            )
            self._data_owned_pipes = [pipe_name]
            self._data_subscribers: dict[int, tuple[str, object]] = {}
        else:
            downstream = f"{pipe_name}-{self._pid}"
            ensure_pipe(downstream)
            self._data_owned_pipes = [downstream]
            self._data_recv = os.fdopen(
                os.open(downstream, os.O_RDWR), "rb", buffering=0
            )
            try:
                self._data_send = os.fdopen(
                    os.open(pipe_name, os.O_RDWR), "wb", buffering=0
                )
            except FileNotFoundError:
                self._data_recv.close()
                remove_pipe(downstream)
                print(
                    f"Error: server pipe '{pipe_name}' not found. Is the server running?"
                )
                raise SystemExit(1)

    # --- subscribe / unsubscribe (server only) ---

    def subscribe(self, pid: int, filepath: str | None = None):
        """Add a downstream pipe for *pid*.  Opens ``<filepath>-<pid>``."""
        if self._data_role is not Role.SERVER:
            raise RuntimeError("subscribe is only available on servers")
        path = f"{filepath or self._data_pipe_name}-{pid}"
        ensure_pipe(path)
        f = os.fdopen(os.open(path, os.O_RDWR), "wb", buffering=0)
        self._data_subscribers[pid] = (path, f)

    def unsubscribe(self, pid: int):
        """Remove the downstream pipe for *pid* and clean up."""
        if self._data_role is not Role.SERVER:
            raise RuntimeError("unsubscribe is only available on servers")
        path, f = self._data_subscribers.pop(pid)
        f.close()
        remove_pipe(path)

    # --- data pipe ---

    def recv_data(self) -> tuple[int | None, bytes]:
        """Read one data frame.

        Server: reads ``[4-byte PID][4-byte length][payload]``; returns ``(pid, payload)``.
        Client: reads ``[4-byte length][payload]``; returns ``(None, payload)``.
        """
        if self._data_role is Role.SERVER:
            (pid,) = struct.unpack(">I", self._data_recv.read(4))
            (length,) = struct.unpack(">I", self._data_recv.read(4))
            return pid, self._data_recv.read(length)
        else:
            (length,) = struct.unpack(">I", self._data_recv.read(4))
            return None, self._data_recv.read(length)

    def send_data(self, data: bytes, pid: int | None = None):
        """Send *data* to one subscriber (*pid* given) or upstream (client).

        Server with pid: send length-prefixed frame to that subscriber.
        Server with pid=None: broadcast to all subscribers.
        Client: prepend own PID then send upstream.
        """
        if self._data_role is Role.SERVER:
            if pid is None:
                for _, f in self._data_subscribers.values():
                    f.write(struct.pack(">I", len(data)))
                    f.write(data)
                    f.flush()
            else:
                subscriber = self._data_subscribers.get(pid)
                if subscriber is None:
                    return
                _, f = subscriber
                f.write(struct.pack(">I", len(data)))
                f.write(data)
                f.flush()
        else:
            self._data_send.write(struct.pack(">II", self._pid, len(data)))
            self._data_send.write(data)
            self._data_send.flush()

    def broadcast_data(self, data: bytes):
        """Send *data* to all subscribers (server only convenience alias)."""
        self.send_data(data, pid=None)

    # --- abstract handler ---

    @abstractmethod
    def data_handler_fn(self, data: bytes, pid: int | None):
        """Called for each incoming data payload.

        *pid* is the sender's PID (server side) or ``None`` (client side).
        """

    # --- listen loop ---

    def stop_data(self):
        """Unblock the listen_data() loop."""
        if not hasattr(self, "_data_stop_w"):
            return
        try:
            os.write(self._data_stop_w, b"\x00")
        except OSError:
            pass

    def listen_data(self) -> threading.Event:
        """Start a background thread that dispatches data until stop_data().

        Returns a threading.Event that is set when the listener thread exits.
        """
        done = threading.Event()

        def _data_loop():
            try:
                while True:
                    readable, _, _ = select.select(
                        [self._data_recv, self._data_stop_r], [], []
                    )
                    if self._data_stop_r in readable:
                        break
                    pid, data = self.recv_data()
                    self.data_handler_fn(data, pid)
            finally:
                done.set()

        self._data_listener_thread = threading.Thread(target=_data_loop, daemon=True)
        self._data_listener_thread.start()
        return done

    def _close_data(self):
        if not hasattr(self, "_data_closed") or self._data_closed:
            return
        self._data_closed = True
        self.stop_data()
        if self._data_listener_thread is not None:
            self._data_listener_thread.join()
            self._data_listener_thread = None
        self._data_recv.close()
        if self._data_role is Role.SERVER:
            for pid in list(self._data_subscribers):
                self.unsubscribe(pid)
        elif hasattr(self, "_data_send"):
            self._data_send.close()
        for fd in (self._data_stop_r, self._data_stop_w):
            try:
                os.close(fd)
            except OSError:
                pass
        for path in self._data_owned_pipes:
            remove_pipe(path)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._close_data()
