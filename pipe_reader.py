#!/usr/bin/env python3
import datetime
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
        <pipe_name>-upstream-cmd    C# → Python  (messages)
        <pipe_name>-downstream-cmd  Python → C#  (messages)
        <pipe_name>-upstream-data   C# → Python  (binary)
        <pipe_name>-downstream-data Python → C#  (binary)
    """

    def __init__(self, pipe_name: str = "/tmp/agent"):
        self._upstream_cmd   = f"{pipe_name}-upstream-cmd"
        self._downstream_cmd = f"{pipe_name}-downstream-cmd"
        self._upstream_data  = f"{pipe_name}-upstream-data"
        self._downstream_data = f"{pipe_name}-downstream-data"
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


# --- command handlers ---

def handle_ping(ch: PipeChannel, _data: str):
    ch.send_message("PONG")


def handle_greet(ch: PipeChannel, data: str):
    name = data if data else "stranger"
    ch.send_message("GREET", f"Hello, {name}!")


def handle_time(ch: PipeChannel, _data: str):
    ch.send_message("TIME", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def handle_echo(ch: PipeChannel, data: str):
    ch.send_message("ECHO", data)


def handle_send_bytes(ch: PipeChannel, _data: str):
    raw = ch.recv_data()
    print(f"  Received {len(raw)} bytes: {list(raw)}")
    ch.send_data(raw)
    ch.send_message("OK", f"echoed {len(raw)} bytes")


HANDLERS = {
    "PING":       handle_ping,
    "GREET":      handle_greet,
    "TIME":       handle_time,
    "ECHO":       handle_echo,
    "SEND_BYTES": handle_send_bytes,
}


def dispatch(ch: PipeChannel, msg: dict):
    command = msg["cmd"].upper()
    data    = msg.get("data", "")
    handler = HANDLERS.get(command)
    if handler:
        handler(ch, data)
    else:
        ch.send_message("ERROR", f"unknown command '{command}'")


def main():
    with PipeChannel() as ch:
        print("Pipes open. Listening for messages (send QUIT to stop)...")
        try:
            while True:
                msg = ch.recv_message()
                if not msg:
                    continue
                print(f"Received: {msg}")
                if msg["cmd"].upper() == "QUIT":
                    ch.send_message("BYE")
                    print("Quit received. Shutting down.")
                    break
                dispatch(ch, msg)
        except KeyboardInterrupt:
            print("\nShutting down.")


if __name__ == "__main__":
    main()
