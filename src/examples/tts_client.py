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

import threading

from named_pipes.tool_client import ToolClient

QUERY = [
    {
        "role": "user",
        # "content": "Tell me a short story about a robot learning to paint.",
        "content": "What is your name?",
    }
]


class _LLMClient(ToolClient):
    """Streaming client for the ChatServer protocol."""

    def __init__(self, on_chunk, on_done):
        super().__init__("chat")
        self._on_chunk = on_chunk
        self._on_done = on_done

    def on_message(self, msg: dict):
        if msg.get("done") is True:
            self._on_done()
        elif "done" in msg:
            self._on_chunk(msg.get("result", ""))


class _TTSClient(ToolClient):
    """Client for the TTSServer protocol."""

    def __init__(self):
        super().__init__("tts")

    def send_text(self, token: str):
        """Send a text chunk to the TTS server."""
        self.send_command("text", data=token)

    def flush(self):
        """Tell the TTS server to synthesise any remaining buffered text."""
        self.send_command("flush")


def main():
    stream_done = threading.Event()

    with _TTSClient() as tts:

        def on_chunk(text: str):
            print(text, end="", flush=True)
            tts.send_text(text)

        def on_done():
            tts.flush()
            stream_done.set()

        with _LLMClient(on_chunk, on_done) as llm:
            print("Subscribed to both servers.")
            print(f"Query: {QUERY[0]['content']!r}\nResponse: ", end="")
            llm.send_command("chat", messages=QUERY)

            stream_done.wait()
            print()  # newline after streamed chunks


if __name__ == "__main__":
    main()
