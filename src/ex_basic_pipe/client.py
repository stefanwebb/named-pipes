"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

import threading

from named_pipes import BasicPipeChannel, Role

PIPE_NAME = "/tmp/basic_pipe"


def main():
    pong_received = threading.Event()

    with BasicPipeChannel(pipe_name=PIPE_NAME, role=Role.CLIENT) as ch:

        @ch.handler("SUBSCRIBED")
        def on_subscribed(msg: dict, pid: int | None):
            print("Subscribed to server. Sending PING...")
            ch.send_message("PING")

        @ch.handler("PONG")
        def on_pong(msg: dict, pid: int | None):
            print("Received PONG!")
            pong_received.set()

        done = ch.listen()
        print("Subscribing to server...")
        ch.send_message("SUBSCRIBE")

        if not pong_received.wait(timeout=5.0):
            print("Timed out waiting for PONG.")
        else:
            print("Ping test passed.")

        ch.send_message("QUIT")
        ch.stop()
        done.wait(timeout=5.0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down.")
