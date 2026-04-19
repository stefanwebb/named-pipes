"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

LLM client: subscribes to the LLM server, demonstrates both streaming
(chat) and blocking (chat_blocking) inference requests.
"""

import threading

from named_pipes.tool_client import ToolClient

STREAMING_QUERY = [{"role": "user", "content": "What is the capital of France?"}]
BLOCKING_QUERY = [
    {"role": "user", "content": "Name three planets in the solar system."}
]


class _LLMClient(ToolClient):
    """Client for the ChatServer protocol."""

    def __init__(self):
        super().__init__("chat")
        self.reply_received = threading.Event()
        self.response: str | None = None

    def on_message(self, msg: dict):
        result = msg.get("result", "")

        if msg.get("done") is True:
            # End-of-stream sentinel from a streaming response.
            self.reply_received.set()
        elif "done" in msg:
            # Streaming chunk — print without newline so chunks flow together.
            print(result, end="", flush=True)
        else:
            # Blocking response — store and signal.
            self.response = result
            self.reply_received.set()


def main():
    with _LLMClient() as ch:
        # --- streaming ---
        print(f"Streaming query: {STREAMING_QUERY[0]['content']!r}")
        print("Response: ", end="")
        ch.send_command("chat", messages=STREAMING_QUERY)
        ch.reply_received.wait()
        print()  # newline after streamed chunks

        # --- blocking ---
        ch.reply_received.clear()
        print(f"\nBlocking query: {BLOCKING_QUERY[0]['content']!r}")
        ch.send_command("chat_blocking", messages=BLOCKING_QUERY)
        ch.reply_received.wait()
        print(f"Response: {ch.response}")


if __name__ == "__main__":
    main()
