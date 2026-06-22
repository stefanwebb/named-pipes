"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

Test client for the named-pipes STT server (any backend implementing the
`stt` interface — see named_pipes.interfaces.stt.STT).

Lists available input devices, prompts you to choose one, then starts
streaming transcription and overwrites the current line in place as the
transcript updates.

Requires the STT server to already be running:
    cpipe --serve stt
"""

import sys
import threading

from named_pipes.tools.client import ToolClient
from named_pipes.utils import _is_fifo_connected


class _LinePrinter:
    def __init__(self) -> None:
        self.last_line_length = 0

    def overwrite(self, text: str) -> None:
        print(f"\r{text}", end="", flush=True)
        if len(text) < self.last_line_length:
            print(" " * (self.last_line_length - len(text)), end="", flush=True)
        self.last_line_length = len(text)

    def newline(self) -> None:
        print()
        self.last_line_length = 0


def main() -> None:
    pipe_path = "/tmp/tool-stt"
    if not _is_fifo_connected(pipe_path):
        print(
            "STT server not running. Start it first with:\n  cpipe --serve stt",
            file=sys.stderr,
        )
        sys.exit(1)

    printer = _LinePrinter()
    devices: list[dict] = []
    devices_received = threading.Event()
    started = threading.Event()

    with ToolClient("stt") as client:

        @client.on("devices")
        def _(msg):
            devices.extend(msg.get("devices", []))
            devices_received.set()

        @client.on("device")
        def _(msg):
            print(f"[device] using index {msg.get('device')}")

        @client.on("speech_start")
        def _(msg):
            printer.newline()
            print("[speech_start]")

        @client.on("speech")
        def _(msg):
            printer.overwrite(msg.get("text", ""))

        @client.on("speech_end")
        def _(msg):
            printer.newline()
            print("[speech_end]")

        @client.on("state_changed")
        def _(msg):
            state = msg.get("state", "")
            print(f"[state_changed] {state}")
            if state == "listening":
                started.set()

        @client.on("error")
        def _(msg):
            print(f"[error] {msg.get('message', '')}", file=sys.stderr)

        client.send_command("list_devices")
        if not devices_received.wait(timeout=5):
            print("Timed out waiting for device list.", file=sys.stderr)
            sys.exit(1)

        print("Available input devices:")
        for d in devices:
            print(f"  [{d['index']}] {d['name']} ({d['channels']} ch)")

        choice = input("\nSelect a device index (blank = server default): ").strip()
        device = int(choice) if choice else None
        client.send_command("set_device", device=device)

        print("\nStarting transcription. Speak into the mic; Ctrl+C to stop.\n")
        client.send_command("start")

        try:
            started.wait(timeout=10)
            threading.Event().wait()
        except KeyboardInterrupt:
            print("\nPausing...")
            client.send_command("pause")


if __name__ == "__main__":
    main()
