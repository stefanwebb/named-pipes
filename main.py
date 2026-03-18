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
            ch.send_message("TIME", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        @ch.handler("ECHO")
        def on_echo(data: str):
            ch.send_message("ECHO", data)

        @ch.handler("SEND_BYTES")
        def on_send_bytes(_data: str):
            raw = ch.recv_data()
            print(f"  Received {len(raw)} bytes: {list(raw)}")
            ch.send_data(raw)
            ch.send_message("OK", f"echoed {len(raw)} bytes")

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
                ch.dispatch(msg)
        except KeyboardInterrupt:
            print("\nShutting down.")


if __name__ == "__main__":
    main()
