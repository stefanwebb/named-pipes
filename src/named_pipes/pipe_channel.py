#!/usr/bin/env python3
import json
import os
import struct

def ensure_pipe(path):
    if not os.path.exists(path):
        os.mkfifo(path)


class PipeChannel:
    """Keeps all four named pipes open for the lifetime of the channel.

    Each pipe is opened O_RDWR so the open call never blocks (no need to
    coordinate with the remote end) and the read end never sees EOF when the
    remote writer temporarily closes its side.

    Pipe paths are derived from `pipe_name`:
        <pipe_name>-cmd-upstream    C# → Python  (messages)
        <pipe_name>-cmd-downstream  Python → C#  (messages)
        <pipe_name>-data-upstream   C# → Python  (binary)
        <pipe_name>-data-downstream Python → C#  (binary)

    Use @ch.handler("<CMD>") to register command handler functions.
    """

    def __init__(self, pipe_name: str = "/tmp/agent"):
        self._upstream_cmd    = f"{pipe_name}-cmd-upstream"
        self._downstream_cmd  = f"{pipe_name}-cmd-downstream"
        self._upstream_data   = f"{pipe_name}-data-upstream"
        self._downstream_data = f"{pipe_name}-data-downstream"
        self._all_pipes = [
            self._upstream_cmd, self._downstream_cmd,
            self._upstream_data, self._downstream_data,
        ]

        for path in self._all_pipes:
            ensure_pipe(path)

        # O_RDWR: non-blocking open + prevents EOF on the read end.
        # We only ever read from _msg_recv / _data_recv and only ever write
        # to _msg_send / _data_send; the unused direction is just a keeper.
        self._msg_recv  = os.fdopen(os.open(self._upstream_cmd,    os.O_RDWR), "r",  buffering=1)
        self._msg_send  = os.fdopen(os.open(self._downstream_cmd,  os.O_RDWR), "w",  buffering=1)
        self._data_recv = os.fdopen(os.open(self._upstream_data,   os.O_RDWR), "rb", buffering=0)
        self._data_send = os.fdopen(os.open(self._downstream_data, os.O_RDWR), "wb", buffering=0)

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

    def listen(self):
        """Block and dispatch messages until a QUIT command is received."""
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

    def dispatch(self, msg: dict):
        cmd  = msg["cmd"].upper()
        data = msg.get("data", "")
        fn   = self._handlers.get(cmd)
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


