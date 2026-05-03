"""
Entry point for launching a ChatServer from a serialised ChatConfig.

Usage:
    python -m named_pipes.chat.launch '<json>'
"""

import json
import sys

from named_pipes.chat.server import ChatConfig, ChatServer


def main():
    if len(sys.argv) < 2:
        print("usage: python -m named_pipes.chat.launch '<config json>'", file=sys.stderr)
        sys.exit(1)

    config = ChatConfig(**json.loads(sys.argv[1]))
    with ChatServer(config) as server:
        done = server.listen()
        print(f"Chat server '{config.name}' listening on /tmp/tool-{config.name}", flush=True)
        done.wait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
