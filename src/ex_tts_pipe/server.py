"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

TTS server: loads Kokoro-82M via mlx-audio and plays synthesised speech in
real time, receiving text tokens over a named pipe using the TTSNamedPipe
protocol.
"""

from named_pipes.tts_named_pipe import TTSNamedPipe


def main():
    with TTSNamedPipe() as ch:
        done = ch.listen()
        print("TTS server listening on /tmp/tool-tts ...")
        done.wait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down.")
