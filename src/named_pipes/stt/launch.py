"""© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en
"""

"""
Entry point for launching an STTServer from a serialised STTConfig.

Usage:
    python -m named_pipes.stt.launch '<json>'
"""

import json
import sys

from named_pipes.stt.server import STTConfig, STTServer


def main():
    if len(sys.argv) < 2:
        print("usage: python -m named_pipes.stt.launch '<config json>'", file=sys.stderr)
        sys.exit(1)

    config = STTConfig(**json.loads(sys.argv[1]))
    with STTServer(config) as server:
        done = server.listen()
        print(f"STT server '{config.name}' listening on /tmp/tool-{config.name}", flush=True)
        done.wait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
