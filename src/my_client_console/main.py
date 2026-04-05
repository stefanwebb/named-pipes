#!/usr/bin/env python3
import threading

from named_pipes import BasicPipeChannel, Role

PIPE_NAME = "/tmp/basic_pipe"


def main():
    pong_received = threading.Event()

    with BasicPipeChannel(pipe_name=PIPE_NAME, role=Role.CLIENT) as ch:

        @ch.handler("SUBSCRIBED")
        def on_subscribed(_msg: dict):
            print("Subscribed to server. Sending PING...")
            ch.send_message("PING")

        @ch.handler("PONG")
        def on_pong(_msg: dict):
            print("Received PONG!")
            pong_received.set()

        done = ch.listen()
        print("Subscribing to server...")
        ch.send_message("SUBSCRIBE")

        if not pong_received.wait(timeout=5.0):
            print("Timed out waiting for PONG.")
        else:
            print("Ping test passed.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down.")
