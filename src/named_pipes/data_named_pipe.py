#!/usr/bin/env python3
import os
import select
import struct
import threading
from abc import ABC, abstractmethod

from named_pipes.text_named_pipe import Role
from named_pipes.utils import ensure_pipe, remove_pipe


class DataNamedPipe(ABC):
    """Base class for binary data named-pipe IPC.

    Servers open a single upstream pipe for receiving and use subscribe()
    to add downstream pipes (keyed by pid) for broadcasting data.

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
        self._data_stop_r, self._data_stop_w = os.pipe()
        self._data_listener_thread: threading.Thread | None = None

        if role is Role.SERVER:
            ensure_pipe(pipe_name)
            self._data_recv = os.fdopen(
                os.open(pipe_name, os.O_RDWR), "rb", buffering=0
            )
            self._owned_pipes = [pipe_name]
            self._subscribers: dict[int, tuple[str, object]] = {}
        else:
            downstream = f"{pipe_name}-{self._pid}"
            ensure_pipe(downstream)
            self._data_recv = os.fdopen(
                os.open(downstream, os.O_RDWR), "rb", buffering=0
            )
            self._owned_pipes = [downstream]

    # --- subscribe / unsubscribe (server only) ---

    def subscribe(self, pid: int, filepath: str):
        """Add a downstream pipe for *pid*.  Opens ``<filepath>-<pid>``."""
        if self._role is not Role.SERVER:
            raise RuntimeError("subscribe is only available on servers")
        path = f"{filepath}-{pid}"
        ensure_pipe(path)
        f = os.fdopen(os.open(path, os.O_RDWR), "wb", buffering=0)
        self._subscribers[pid] = (path, f)

    def unsubscribe(self, pid: int):
        """Remove the downstream pipe for *pid* and clean up."""
        if self._role is not Role.SERVER:
            raise RuntimeError("unsubscribe is only available on servers")
        path, f = self._subscribers.pop(pid)
        f.close()
        remove_pipe(path)

    # --- data pipe (4-byte big-endian length prefix) ---

    def recv_data(self) -> bytes:
        (length,) = struct.unpack(">I", self._data_recv.read(4))
        return self._data_recv.read(length)

    def send_data(self, data: bytes):
        """Broadcast data to all downstream subscribers."""
        for _, f in self._subscribers.values():
            f.write(struct.pack(">I", len(data)))
            f.write(data)
            f.flush()

    # --- abstract handler ---

    @abstractmethod
    def data_handler_fn(self, data: bytes):
        """Called for each incoming data payload."""

    # --- listen loop ---

    def stop(self):
        """Unblock the listen() loop."""
        os.write(self._data_stop_w, b"\x00")

    def listen(self) -> threading.Event:
        """Start a background thread that dispatches data until stop().

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
                    data = self.recv_data()
                    self.data_handler_fn(data)
            finally:
                done.set()

        self._data_listener_thread = threading.Thread(target=_data_loop, daemon=True)
        self._data_listener_thread.start()
        return done

    def _close(self):
        self.stop()
        if self._data_listener_thread is not None:
            self._data_listener_thread.join()
            self._data_listener_thread = None
        self._data_recv.close()
        if self._role is Role.SERVER:
            for pid in list(self._subscribers):
                self.unsubscribe(pid)
        for fd in (self._data_stop_r, self._data_stop_w):
            try:
                os.close(fd)
            except OSError:
                pass
        for path in self._owned_pipes:
            remove_pipe(path)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._close()
