#!/usr/bin/env python3
import datetime

from named_pipes import PipeChannel


def main():
    with PipeChannel() as ch:

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
            print(f"  Received {len(raw)} bytes: {list(raw)}")
            ch.send_data(raw)
            ch.send_message("OK", f"echoed {len(raw)} bytes")

        done = ch.listen()
        done.wait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down.")
