#!/usr/bin/env python3
"""Send a test CHAT query to a running TransformersPipeChannel server."""

import json
import threading

from named_pipes import BasicPipeChannel, Role

QUERY = [{"role": "user", "content": "What is the capital of France?"}]


def main():
    reply_received = threading.Event()

    with BasicPipeChannel(role=Role.CLIENT) as ch:

        @ch.handler("CHAT_RESPONSE")
        def on_chat_response(data: str):
            print(f"Response: {data}")
            reply_received.set()
            ch.stop()

        @ch.handler("ERROR")
        def on_error(data: str):
            print(f"Error: {data}")
            reply_received.set()
            ch.stop()

        ch.listen()
        print(f"Sending: {QUERY[0]['content']}")
        ch.send_message("CHAT", json.dumps(QUERY))
        reply_received.wait()


if __name__ == "__main__":
    main()
