#!/usr/bin/env python3
import json
import os
import struct
import threading
from enum import Enum


class Role(Enum):
    SERVER = "server"
    CLIENT = "client"


def ensure_pipe(path):
    if not os.path.exists(path):
        os.mkfifo(path)


class PipeChannel:
    """Keeps all four named pipes open for the lifetime of the channel.

    Each pipe is opened O_RDWR so the open call never blocks (no need to
    coordinate with the remote end) and the read end never sees EOF when the
    remote writer temporarily closes its side.

    Pipe paths are derived from `pipe_name`:
        <pipe_name>-cmd-upstream    client → server  (messages)
        <pipe_name>-cmd-downstream  server → client  (messages)
        <pipe_name>-data-upstream   client → server  (binary)
        <pipe_name>-data-downstream server → client  (binary)

    `role` determines which pipes are used for send vs. receive:
        Role.SERVER  reads upstream,   writes downstream
        Role.CLIENT  reads downstream, writes upstream

    Use @ch.handler("<CMD>") to register command handler functions.
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

        # O_RDWR: non-blocking open + prevents EOF on the read end.
        # We only ever read from _msg_recv / _data_recv and only ever write
        # to _msg_send / _data_send; the unused direction is just a keeper.
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

        self._handlers: dict[str, callable] = {}

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

    # --- handler registration and dispatch ---

    def handler(self, cmd: str):
        """Decorator that registers a function as the handler for `cmd`."""

        def decorator(fn):
            self._handlers[cmd] = fn
            return fn

        return decorator

    def listen(self) -> threading.Event:
        """Start a background thread that dispatches messages until QUIT.

        Returns a threading.Event that is set when the listener thread exits,
        so the caller can do ``done = ch.listen(); done.wait()``.
        """
        done = threading.Event()

        def _loop():
            print("Pipes open. Listening for messages (send QUIT to stop)...")
            try:
                while True:
                    msg = self.recv_message()
                    if not msg:
                        continue
                    print(f"Received: {msg}")
                    if msg["cmd"].upper() == "QUIT":
                        self.send_message("BYE")
                        print("Quit received. Shutting down.")
                        break
                    self.dispatch(msg)
            except KeyboardInterrupt:
                print("\nShutting down.")
            finally:
                done.set()

        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        return done

    def dispatch(self, msg: dict):
        cmd = msg["cmd"].upper()
        data = msg.get("data", "")
        fn = self._handlers.get(cmd)
        if fn:
            fn(data)
        else:
            self.send_message("ERROR", f"unknown command '{cmd}'")

    def close(self):
        for f in (self._msg_recv, self._msg_send, self._data_recv, self._data_send):
            f.close()
        for path in self._all_pipes:
            if os.path.exists(path):
                os.remove(path)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
