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

import json
import threading

from named_pipes.text_named_pipe import Role, TextNamedPipe


class _STTClient(TextNamedPipe):
    """Minimal subscriber for the STTServer / ToolServer protocol."""

    def __init__(self):
        super().__init__("/tmp/tool-stt", Role.CLIENT)
        self.subscribed = threading.Event()

    def msg_handler_fn(self, msg: dict, pid: int | None):
        if msg.get("result") == "subscribed":
            self.subscribed.set()
            return

        if "event" in msg:
            event = msg["event"]
            if event == "speech_start":
                print("\n[speech_start] ", end="", flush=True)
            elif event == "speech_end":
                print(" [speech_end]", flush=True)
            return

        if "result" in msg:
            print(msg["result"], end="", flush=True)


def main():
    with _STTClient() as stt:
        stt.listen()
        stt.send_message(json.dumps({"pid": stt._pid, "cmd": "subscribe"}))
        stt.subscribed.wait()
        print("Subscribed to /tmp/tool-stt. Speak into the mic; Ctrl+C to stop.")

        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print("\nUnsubscribing.")
            stt.send_message(json.dumps({"pid": stt._pid, "cmd": "unsubscribe"}))


if __name__ == "__main__":
    main()
