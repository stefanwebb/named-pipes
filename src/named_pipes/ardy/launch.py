"""© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en
"""

"""
Entry point for launching an ArdyServer from a serialised ArdyConfig.

Usage:
    python -m named_pipes.ardy.launch
    python -m named_pipes.ardy.launch '{"model": "nvidia/ARDY-Core-RP-20FPS-Horizon8", "device": "mps"}'
"""

import json
import sys

from named_pipes.ardy.server import ArdyConfig, ArdyServer


def main():
    config = ArdyConfig(**json.loads(sys.argv[1])) if len(sys.argv) > 1 else ArdyConfig()
    with ArdyServer(config) as server:
        done = server.listen()
        print(f"ARDY server '{config.name}' listening on /tmp/tool-{config.name}", flush=True)
        done.wait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down.")
