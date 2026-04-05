"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

LLM client: subscribes to the LLM server, sends a single chat query,
and prints the response.
"""

import json
import threading

from named_pipes.text_named_pipe import Role, TextNamedPipe

QUERY = [{"role": "user", "content": "What is the capital of France?"}]


class _LLMClient(TextNamedPipe):
    """Minimal client for the ToolNamedPipe / ChatNamedPipe protocol."""

    def __init__(self):
        super().__init__("/tmp/tool-llm", Role.CLIENT)
        self.subscribed = threading.Event()
        self.response: str | None = None
        self.reply_received = threading.Event()

    def msg_handler_fn(self, msg: dict):
        result = msg.get("result", "")
        if result == "subscribed":
            self.subscribed.set()
        else:
            self.response = result
            self.reply_received.set()


def main():
    with _LLMClient() as ch:
        ch.listen()

        ch.send_message(json.dumps({"pid": ch._pid, "cmd": "subscribe"}))
        ch.subscribed.wait()

        print(f"Sending: {QUERY[0]['content']}")
        ch.send_message(json.dumps({"pid": ch._pid, "cmd": "chat", "messages": QUERY}))

        ch.reply_received.wait()
        print(f"Response: {ch.response}")


if __name__ == "__main__":
    main()
