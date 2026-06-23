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
    """Overwrites an in-place block of one or more terminal lines."""

    def __init__(self) -> None:
        self.height = 0

    def overwrite(self, *lines: str) -> None:
        rows = max(len(lines), self.height)
        if self.height:
            if self.height > 1:
                print(f"\x1b[{self.height - 1}A", end="")
            print("\r", end="")
        for i in range(rows):
            line = lines[i] if i < len(lines) else ""
            end = "\n" if i < rows - 1 else ""
            print(f"\x1b[2K{line}", end=end, flush=True)
        self.height = rows

    def newline(self) -> None:
        if self.height:
            print()
        self.height = 0


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
    speech_ended = threading.Event()

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
            speech_ended.clear()
            printer.newline()
            print("[speech_start]")

        @client.on("speech")
        def _(msg):
            words = msg.get("words")
            # The forced aligner runs out-of-process and reports back after the
            # fact, so a "speech" event with words can arrive well after this
            # utterance's speech_end. Only print the timestamps then, instead
            # of re-printing the live partial text again.
            if words:
                if speech_ended.is_set():
                    print(
                        " ".join(
                            f"[{w['start']:.3f}–{w['end']:.3f}] {w['word']}"
                            for w in words
                        )
                    )
                return
            printer.overwrite(msg.get("text", ""))

        @client.on("speech_end")
        def _(msg):
            printer.newline()
            print("[speech_end]")
            speech_ended.set()

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
