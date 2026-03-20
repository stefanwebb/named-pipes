#!/usr/bin/env python3
import json
import os
import select
import struct
import threading
from abc import ABC, abstractmethod
from enum import Enum


class Role(Enum):
    SERVER = "server"
    CLIENT = "client"


def ensure_pipe(path):
    if not os.path.exists(path):
        os.mkfifo(path)


class AbstractPipeChannel(ABC):
    """Base class for named-pipe IPC channels.

    Manages four named pipes and a background listen loop.  Subclasses
    must implement ``msg_handler_fn`` and ``data_handler_fn`` to handle
    incoming messages and data payloads respectively.

    Pipe paths are derived from `pipe_name`:
        <pipe_name>-cmd-upstream    client → server  (messages)
        <pipe_name>-cmd-downstream  server → client  (messages)
        <pipe_name>-data-upstream   client → server  (binary)
        <pipe_name>-data-downstream server → client  (binary)

    `role` determines which pipes are used for send vs. receive:
        Role.SERVER  reads upstream,   writes downstream
        Role.CLIENT  reads downstream, writes upstream
    """

    def __init__(self, pipe_name: str = "/tmp/agent", role: Role = Role.SERVER):
        self._role = role

        upstream_cmd = f"{pipe_name}-cmd-upstream"
        downstream_cmd = f"{pipe_name}-cmd-downstream"
        upstream_data = f"{pipe_name}-data-upstream"
        downstream_data = f"{pipe_name}-data-downstream"
        self._all_pipes = [upstream_cmd, downstream_cmd, upstream_data, downstream_data]

        for path in self._all_pipes:
            ensure_pipe(path)

        if role is Role.SERVER:
            recv_cmd, send_cmd = upstream_cmd, downstream_cmd
            recv_data, send_data = upstream_data, downstream_data
        else:
            recv_cmd, send_cmd = downstream_cmd, upstream_cmd
            recv_data, send_data = downstream_data, upstream_data

        self._msg_recv = os.fdopen(os.open(recv_cmd, os.O_RDWR), "r", buffering=1)
        self._msg_send = os.fdopen(os.open(send_cmd, os.O_RDWR), "w", buffering=1)
        self._data_recv = os.fdopen(os.open(recv_data, os.O_RDWR), "rb", buffering=0)
        self._data_send = os.fdopen(os.open(send_data, os.O_RDWR), "wb", buffering=0)

        self._stop_r, self._stop_w = os.pipe()

        self._listener_thread: threading.Thread | None = None
        self._data_listener_thread: threading.Thread | None = None

    # --- message pipe ---

    def recv_message(self) -> dict:
        line = self._msg_recv.readline().rstrip("\n")
        return json.loads(line)

    def send_message(self, cmd: str, data: str = ""):
        self._msg_send.write(json.dumps({"cmd": cmd, "data": data}) + "\n")
        self._msg_send.flush()

    # --- data pipe (4-byte big-endian length prefix) ---

    def recv_data(self) -> bytes:
        (length,) = struct.unpack(">I", self._data_recv.read(4))
        return self._data_recv.read(length)

    def send_data(self, data: bytes):
        self._data_send.write(struct.pack(">I", len(data)))
        self._data_send.write(data)
        self._data_send.flush()

    # --- abstract handlers ---

    @abstractmethod
    def msg_handler_fn(self, msg: dict):
        """Called for each incoming message (excluding QUIT, which is handled by the loop)."""

    @abstractmethod
    def data_handler_fn(self, data: bytes):
        """Called for each incoming data payload."""

    # --- listen loop ---

    def stop(self):
        """Unblock the listen() loop without closing the real named pipes."""
        os.write(self._stop_w, b"\x00")

    def listen(self) -> threading.Event:
        """Start background threads that dispatch messages and data until QUIT or stop().

        Returns a threading.Event that is set when both listener threads have exited.
        """
        done = threading.Event()
        threads_remaining = [2]
        lock = threading.Lock()

        def _mark_done():
            with lock:
                threads_remaining[0] -= 1
                if threads_remaining[0] == 0:
                    done.set()

        def _msg_loop():
            print("Pipes open. Listening for messages (send QUIT to stop)...")
            try:
                while True:
                    readable, _, _ = select.select(
                        [self._msg_recv, self._stop_r], [], []
                    )
                    if self._stop_r in readable:
                        break
                    msg = self.recv_message()
                    if not msg:
                        continue
                    print(f"Received: {msg}")
                    if msg["cmd"].upper() == "QUIT":
                        self.send_message("BYE")
                        print("Quit received. Shutting down.")
                        self.stop()
                        break
                    self.msg_handler_fn(msg)
            finally:
                _mark_done()

        def _data_loop():
            try:
                while True:
                    readable, _, _ = select.select(
                        [self._data_recv, self._stop_r], [], []
                    )
                    if self._stop_r in readable:
                        break
                    data = self.recv_data()
                    self.data_handler_fn(data)
            finally:
                _mark_done()

        self._listener_thread = threading.Thread(target=_msg_loop, daemon=True)
        self._data_listener_thread = threading.Thread(target=_data_loop, daemon=True)
        self._listener_thread.start()
        self._data_listener_thread.start()
        return done

    def _close(self):
        self.stop()
        if self._listener_thread is not None:
            self._listener_thread.join()
            self._listener_thread = None
        if self._data_listener_thread is not None:
            self._data_listener_thread.join()
            self._data_listener_thread = None
        for f in (self._msg_recv, self._msg_send, self._data_recv, self._data_send):
            f.close()
        for fd in (self._stop_r, self._stop_w):
            try:
                os.close(fd)
            except OSError:
                pass
        for path in self._all_pipes:
            if os.path.exists(path):
                os.remove(path)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._close()
