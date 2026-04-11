"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

LLM→TTS client: sends a chat query to the LLM server, then forwards the
response token-by-token to the TTS server for real-time speech synthesis.

Requires both servers to be running before starting this client:
    python src/ex_chat_pipe/server.py   (listens on /tmp/tool-chat)
    python src/ex_tts_pipe/server.py    (listens on /tmp/tool-tts)
"""

import json
import re
import threading

from named_pipes.text_named_pipe import Role, TextNamedPipe

QUERY = [
    {
        "role": "user",
        "content": "Tell me a short story about a robot learning to paint.",
    }
]

# Split response into word-sized tokens to simulate a streaming LLM.
_TOKEN_RE = re.compile(r"\S+\s*")


class _LLMClient(TextNamedPipe):
    """Minimal client for the ToolNamedPipe / ChatNamedPipe protocol."""

    def __init__(self):
        super().__init__("/tmp/tool-chat", Role.CLIENT)
        self.subscribed = threading.Event()
        self.response: str | None = None
        self.reply_received = threading.Event()

    def msg_handler_fn(self, msg: dict, pid: int | None):
        result = msg.get("result", "")
        if result == "subscribed":
            self.subscribed.set()
        else:
            self.response = result
            self.reply_received.set()


class _TTSClient(TextNamedPipe):
    """Minimal client for the TTSNamedPipe / ToolNamedPipe protocol."""

    def __init__(self):
        super().__init__("/tmp/tool-tts", Role.CLIENT)
        self.subscribed = threading.Event()

    def msg_handler_fn(self, msg: dict, pid: int | None):
        if msg.get("result") == "subscribed":
            self.subscribed.set()

    def send_text(self, token: str):
        """Send a text token to the TTS server."""
        self.send_message(json.dumps({"pid": self._pid, "cmd": "text", "data": token}))

    def flush(self):
        """Tell the TTS server to synthesise any remaining buffered text."""
        self.send_message(json.dumps({"pid": self._pid, "cmd": "flush"}))


def main():
    with _LLMClient() as llm, _TTSClient() as tts:
        llm.listen()
        tts.listen()

        # Subscribe to both servers.
        llm.send_message(json.dumps({"pid": llm._pid, "cmd": "subscribe"}))
        tts.send_message(json.dumps({"pid": tts._pid, "cmd": "subscribe"}))
        llm.subscribed.wait()
        tts.subscribed.wait()
        print("Subscribed to both servers.")

        # Send the chat query to the LLM server.
        print(f"Query: {QUERY[0]['content']!r}")
        llm.send_message(
            json.dumps({"pid": llm._pid, "cmd": "chat", "messages": QUERY})
        )

        # Wait for the full LLM response.
        llm.reply_received.wait()
        response = llm.response
        print(f"LLM response: {response!r}")

        # Forward response word-by-word to the TTS server, simulating a token stream.
        print("Forwarding to TTS server…")
        for token in _TOKEN_RE.findall(response):
            tts.send_text(token)

        # Flush any remaining text (the final sentence fragment).
        tts.flush()

        # Gracefully exit both servers.
        llm.send_message(json.dumps({"pid": llm._pid, "cmd": "unsubscribe"}))
        tts.send_message(json.dumps({"pid": tts._pid, "cmd": "unsubscribe"}))


if __name__ == "__main__":
    main()
