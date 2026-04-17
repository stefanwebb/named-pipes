"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

LLM server: loads Qwen3.5-0.8B via Transformers and serves chat requests
over a named pipe using the ChatNamedPipe / ToolNamedPipe protocol.
"""

from named_pipes.chat_named_pipe import ChatNamedPipe


def main():
    with ChatNamedPipe() as ch:
        done = ch.listen()
        print("LLM server listening on /tmp/tool-chat ...")
        done.wait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down.")
