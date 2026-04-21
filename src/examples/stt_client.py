"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

STT subscriber: connects to the STT server on /tmp/tool-stt, subscribes,
and prints each broadcast message until Ctrl+C.

Requires the STT server to be running first:
    cpipe --serve stt
"""

import threading

from named_pipes.tool_client import ToolClient


class _STTClient(ToolClient):
    """Subscriber for the STTServer protocol."""

    def __init__(self):
        super().__init__("stt")

        @self.on("token")
        def _(msg):
            print(msg.get("text", ""), end="", flush=True)

        @self.on("speech_start")
        def _(msg):
            print("[speech_start] ", end="", flush=True)

        @self.on("speech_end")
        def _(msg):
            print("[speech_end]", flush=True)

        @self.on("state_changed")
        def _(msg):
            print(f"\n[state_changed] {msg.get('state', '')}", flush=True)


def main():
    with _STTClient() as stt:
        print("Subscribed to /tmp/tool-stt. Speak into the mic; Ctrl+C to stop.")

        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print("\nUnsubscribing.")


if __name__ == "__main__":
    main()
