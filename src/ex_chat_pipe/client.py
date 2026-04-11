"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

LLM client: subscribes to the LLM server, demonstrates both streaming
(chat) and blocking (chat_blocking) inference requests.
"""

import json
import threading

from named_pipes.text_named_pipe import Role, TextNamedPipe

STREAMING_QUERY = [{"role": "user", "content": "What is the capital of France?"}]
BLOCKING_QUERY = [
    {"role": "user", "content": "Name three planets in the solar system."}
]


class _LLMClient(TextNamedPipe):
    """Minimal client for the ToolNamedPipe / ChatNamedPipe protocol."""

    def __init__(self):
        super().__init__("/tmp/tool-chat", Role.CLIENT)
        self.subscribed = threading.Event()
        # Set when the stream-done sentinel (done=True) or a blocking reply arrives.
        self.reply_received = threading.Event()
        self.response: str | None = None

    def msg_handler_fn(self, msg: dict, pid: int | None):
        result = msg.get("result", "")

        if result == "subscribed":
            self.subscribed.set()
            return

        if msg.get("done") is True:
            # End-of-stream sentinel from a streaming response.
            self.reply_received.set()
            return

        if "done" in msg:
            # Streaming chunk — print without newline so chunks flow together.
            print(result, end="", flush=True)
        else:
            # Blocking response — store and signal.
            self.response = result
            self.reply_received.set()


def main():
    with _LLMClient() as ch:
        ch.listen()
        ch.send_message(json.dumps({"pid": ch._pid, "cmd": "subscribe"}))
        ch.subscribed.wait()

        # --- streaming ---
        print(f"Streaming query: {STREAMING_QUERY[0]['content']!r}")
        print("Response: ", end="")
        ch.send_message(
            json.dumps({"pid": ch._pid, "cmd": "chat", "messages": STREAMING_QUERY})
        )
        ch.reply_received.wait()
        print()  # newline after streamed chunks

        # --- blocking ---
        ch.reply_received.clear()
        print(f"\nBlocking query: {BLOCKING_QUERY[0]['content']!r}")
        ch.send_message(
            json.dumps(
                {"pid": ch._pid, "cmd": "chat_blocking", "messages": BLOCKING_QUERY}
            )
        )
        ch.reply_received.wait()
        print(f"Response: {ch.response}")

        ch.send_message(json.dumps({"pid": ch._pid, "cmd": "unsubscribe"}))


if __name__ == "__main__":
    main()
