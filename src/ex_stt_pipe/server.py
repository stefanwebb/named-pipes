"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

STT server: loads Voxtral Realtime via vendored voxtral, captures the default
microphone, and broadcasts transcribed tokens plus VAD speech-start /
speech-end events to all subscribers of /tmp/tool-stt.
"""

from named_pipes.stt import STTNamedPipe


def main():
    with STTNamedPipe() as ch:
        done = ch.listen()
        print("STT server listening on /tmp/tool-stt ...")
        done.wait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down.")
