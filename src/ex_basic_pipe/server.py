"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

import datetime

from named_pipes import BasicPipeChannel, Role

PIPE_NAME = "/tmp/basic_pipe"


def main():
    with BasicPipeChannel(pipe_name=PIPE_NAME, role=Role.SERVER) as ch:

        @ch.handler("SUBSCRIBE")
        def on_subscribe(msg: dict):
            pid = msg["pid"]
            print(f"Client {pid} subscribed to server {ch._pid}")
            ch.subscribe(pid)
            ch.send_message("SUBSCRIBED")

        @ch.handler("PING")
        def on_ping(_msg: dict):
            print("Event: on_ping")
            ch.send_message("PONG")

        @ch.handler("GREET")
        def on_greet(msg: dict):
            print("Event: on_greet")
            name = msg["data"] or "stranger"
            ch.send_message("GREET", f"Hello, {name}!")

        @ch.handler("TIME")
        def on_time(_msg: dict):
            print("Event: on_time")
            ch.send_message(
                "TIME", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )

        @ch.handler("ECHO")
        def on_echo(msg: dict):
            print("Event: on_echo")
            ch.send_message("ECHO", msg["data"])

        @ch.handler("QUIT")
        def on_quit(_msg: dict):
            print("Event: on_quit")
            ch.send_message("BYE")
            ch.stop()

        @ch.handler("SEND_BYTES")
        def on_send_bytes(_msg: dict):
            print("Event: on_send_bytes")

        @ch.data_handler
        def on_data(raw: bytes):
            print(f"  Received {len(raw)} bytes: {list(raw)}")
            ch.send_data(raw)
            ch.send_message("OK", f"echoed {len(raw)} bytes")

        done = ch.listen()
        print("Listening to open pipe...")
        done.wait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down.")
