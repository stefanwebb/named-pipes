#!/usr/bin/env python3
"""Subprocess server for C# PipeChannel integration tests.

Usage: python3 tests/server_main.py [pipe_name]
  pipe_name defaults to /tmp/agent
"""

import datetime
import sys

from named_pipes import PipeChannel


def main():
    pipe_name = sys.argv[1] if len(sys.argv) > 1 else "/tmp/agent"

    with PipeChannel(pipe_name) as ch:

        @ch.handler("PING")
        def on_ping(_data: str):
            ch.send_message("PONG")

        @ch.handler("GREET")
        def on_greet(data: str):
            name = data or "stranger"
            ch.send_message("GREET", f"Hello, {name}!")

        @ch.handler("TIME")
        def on_time(_data: str):
            ch.send_message(
                "TIME", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )

        @ch.handler("ECHO")
        def on_echo(data: str):
            ch.send_message("ECHO", data)

        @ch.handler("SEND_BYTES")
        def on_send_bytes(_data: str):
            raw = ch.recv_data()
            ch.send_data(raw)
            ch.send_message("OK", f"echoed {len(raw)} bytes")

        print("Pipes open. Listening...", flush=True)

        try:
            while True:
                msg = ch.recv_message()
                if not msg:
                    continue
                if msg["cmd"].upper() == "QUIT":
                    ch.send_message("BYE")
                    break
                ch.dispatch(msg)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
