"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

LLM→TTS client: streams a chat query to the LLM server and forwards each
token chunk to the TTS server in real time for speech synthesis.

Requires both servers to be running before starting this client:
    cpipe --serve chat   (listens on /tmp/tool-chat)
    cpipe --serve tts    (listens on /tmp/tool-tts)
"""

import json
import threading

from named_pipes.text_named_pipe import Role, TextNamedPipe

QUERY = [
    {
        "role": "user",
        # "content": "Tell me a short story about a robot learning to paint.",
        "content": "What is your name?",
    }
]


class _LLMClient(TextNamedPipe):
    """Minimal streaming client for the ToolServer / ChatServer protocol."""

    def __init__(self, on_chunk, on_done):
        super().__init__("/tmp/tool-chat", Role.CLIENT)
        self.subscribed = threading.Event()
        self._on_chunk = on_chunk
        self._on_done = on_done

    def msg_handler_fn(self, msg: dict, pid: int | None):
        if msg.get("result") == "subscribed":
            self.subscribed.set()
            return

        if msg.get("done") is True:
            self._on_done()
            return

        if "done" in msg:
            # Streaming chunk.
            self._on_chunk(msg.get("result", ""))


class _TTSClient(TextNamedPipe):
    """Minimal client for the TTSServer / ToolServer protocol."""

    def __init__(self):
        super().__init__("/tmp/tool-tts", Role.CLIENT)
        self.subscribed = threading.Event()

    def msg_handler_fn(self, msg: dict, pid: int | None):
        if msg.get("result") == "subscribed":
            self.subscribed.set()

    def send_text(self, token: str):
        """Send a text chunk to the TTS server."""
        self.send_message(json.dumps({"pid": self._pid, "cmd": "text", "data": token}))

    def flush(self):
        """Tell the TTS server to synthesise any remaining buffered text."""
        self.send_message(json.dumps({"pid": self._pid, "cmd": "flush"}))


def main():
    stream_done = threading.Event()

    with _TTSClient() as tts:
        tts.listen()
        tts.send_message(json.dumps({"pid": tts._pid, "cmd": "subscribe"}))
        tts.subscribed.wait()

        def on_chunk(text: str):
            print(text, end="", flush=True)
            tts.send_text(text)

        def on_done():
            tts.flush()
            stream_done.set()

        with _LLMClient(on_chunk, on_done) as llm:
            llm.listen()
            llm.send_message(json.dumps({"pid": llm._pid, "cmd": "subscribe"}))
            llm.subscribed.wait()

            print("Subscribed to both servers.")
            print(f"Query: {QUERY[0]['content']!r}\nResponse: ", end="")
            llm.send_message(
                json.dumps({"pid": llm._pid, "cmd": "chat", "messages": QUERY})
            )

            stream_done.wait()
            print()  # newline after streamed chunks

            llm.send_message(json.dumps({"pid": llm._pid, "cmd": "unsubscribe"}))

        tts.send_message(json.dumps({"pid": tts._pid, "cmd": "unsubscribe"}))


if __name__ == "__main__":
    main()
