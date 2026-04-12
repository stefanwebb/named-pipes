"""
cpipe — send a command to a named-pipe server, like curl for pipes.

© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en
"""

import argparse
import json
import os
import sys
import threading

from named_pipes.text_named_pipe import Role, TextNamedPipe


class _CpipeClient(TextNamedPipe):
    """Single-shot client: connects, sends one command, prints the response."""

    def __init__(self, pipe_name: str):
        super().__init__(pipe_name, Role.CLIENT)
        self.subscribed = threading.Event()
        self.response_received = threading.Event()

    def msg_handler_fn(self, msg: dict, pid: int | None):
        # --- subscribe acknowledgements ---
        # Tool protocol: {"result": "subscribed"}
        if msg.get("result") == "subscribed":
            self.subscribed.set()
            return

        # Basic protocol: {"cmd": "SUBSCRIBED", ...}
        if msg.get("cmd", "").upper() == "SUBSCRIBED":
            self.subscribed.set()
            return

        # --- streaming (tool protocol chunks) ---
        # End sentinel: {"result": "", "done": true}
        if msg.get("done") is True:
            print()  # newline after streamed tokens
            self.response_received.set()
            return

        # In-flight chunk: {"result": "<token>", "done": false}
        if "done" in msg:
            print(msg.get("result", ""), end="", flush=True)
            return

        # --- one-shot responses ---
        result = msg.get("result")
        if result is not None:
            # Tool protocol response
            print(result)
        elif "cmd" in msg:
            # Basic protocol response: {"cmd": "PONG", "data": "...", "pid": ...}
            cmd = msg["cmd"]
            data = msg.get("data", "")
            print(f"{cmd}: {data}" if data else cmd)
        else:
            # Unknown format — dump raw JSON
            print(json.dumps(msg))

        self.response_received.set()


def _resolve_pipe(pipe: str) -> tuple[str, bool]:
    """Return (absolute_pipe_path, is_tool_protocol).

    Rules:
    - Bare name (no slash), e.g. "chat"   → /tmp/tool-chat  (tool protocol)
    - Path starting with /tmp/tool-        → tool protocol
    - Any other absolute path              → basic protocol
    """
    if "/" not in pipe:
        return f"/tmp/tool-{pipe}", True
    last_component = pipe.rstrip("/").rsplit("/", 1)[-1]
    return pipe, last_component.startswith("tool-")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="cpipe",
        description="Send a command to a named-pipe server (like curl for pipes).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  cpipe chat description                       get tool description
  cpipe /tmp/tool-chat help                    get help text
  cpipe chat exit                              shut down the server
  cpipe chat ping                              send a custom command
  cpipe chat greet -d Alice                    send data with a command
  cpipe chat chat -j '{"messages":[...]}'      merge extra JSON fields
  cpipe /tmp/basic_pipe PING --basic           basic-protocol PING
  cpipe /tmp/basic_pipe GREET -d Bob --basic   basic-protocol GREET with data
""",
    )
    parser.add_argument(
        "pipe",
        metavar="PIPE",
        help="pipe path (/tmp/tool-chat) or bare tool name (chat)",
    )
    parser.add_argument(
        "cmd",
        metavar="CMD",
        help="command to send (e.g. description, help, ping)",
    )
    parser.add_argument(
        "data",
        metavar="DATA",
        nargs="?",
        help="optional data payload (JSON value or plain text)",
    )
    parser.add_argument(
        "-d",
        "--data",
        dest="data_opt",
        metavar="DATA",
        help="data payload (alternative to positional DATA)",
    )
    parser.add_argument(
        "-j",
        "--json",
        metavar="JSON",
        help="extra JSON object fields to merge into the request",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=5.0,
        metavar="SECS",
        help="response timeout in seconds (default: 5.0)",
    )
    parser.add_argument(
        "-n",
        "--no-wait",
        action="store_true",
        help="fire-and-forget: send without waiting for a response",
    )
    parser.add_argument(
        "--no-subscribe",
        action="store_true",
        help="skip the subscribe/unsubscribe handshake",
    )
    parser.add_argument(
        "--basic",
        action="store_true",
        help="force basic pipe protocol (SUBSCRIBE/SUBSCRIBED handshake)",
    )
    parser.add_argument(
        "--tool",
        action="store_true",
        help="force tool protocol (subscribe/unsubscribe handshake)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="print sent messages and status to stderr",
    )
    args = parser.parse_args(argv)

    pipe, auto_tool = _resolve_pipe(args.pipe)

    # Explicit flags override auto-detection
    if args.tool:
        use_tool_protocol = True
    elif args.basic:
        use_tool_protocol = False
    else:
        use_tool_protocol = auto_tool

    do_subscribe = not args.no_subscribe

    # Validate pipe exists
    if not os.path.exists(pipe):
        print(f"cpipe: pipe not found: {pipe}", file=sys.stderr)
        print(
            f"cpipe: is the server running?  (expected FIFO at {pipe})",
            file=sys.stderr,
        )
        sys.exit(1)

    # Resolve data payload (positional wins over -d)
    raw_data = args.data or args.data_opt

    # Parse --json extra fields
    extra: dict = {}
    if args.json:
        try:
            extra = json.loads(args.json)
            if not isinstance(extra, dict):
                raise ValueError("--json value must be a JSON object (dict)")
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"cpipe: invalid --json value: {exc}", file=sys.stderr)
            sys.exit(1)

    def _log(msg: str):
        if args.verbose:
            print(f"[cpipe] {msg}", file=sys.stderr)

    try:
        with _CpipeClient(pipe) as client:
            pid = client._pid
            client.listen()

            # ----------------------------------------------------------------
            # Subscribe handshake
            # ----------------------------------------------------------------
            if do_subscribe:
                if use_tool_protocol:
                    sub_msg = json.dumps({"pid": pid, "cmd": "subscribe"})
                else:
                    sub_msg = json.dumps({"cmd": "SUBSCRIBE", "data": "", "pid": pid})

                _log(f"-> {sub_msg}")
                client.send_message(sub_msg)

                if not client.subscribed.wait(timeout=args.timeout):
                    print(
                        "cpipe: timed out waiting for subscribe acknowledgement",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                _log("subscribed")

            # ----------------------------------------------------------------
            # Build and send command message
            # ----------------------------------------------------------------
            if use_tool_protocol:
                msg: dict = {"pid": pid, "cmd": args.cmd}
            else:
                msg = {"cmd": args.cmd.upper(), "data": "", "pid": pid}

            if raw_data is not None:
                try:
                    parsed_data = json.loads(raw_data)
                except json.JSONDecodeError:
                    parsed_data = raw_data
                msg["data"] = parsed_data

            msg.update(extra)

            request = json.dumps(msg)
            _log(f"-> {request}")
            client.send_message(request)

            # ----------------------------------------------------------------
            # Wait for response
            # ----------------------------------------------------------------
            if not args.no_wait:
                received = client.response_received.wait(timeout=args.timeout)
                if not received:
                    print("\ncpipe: timed out waiting for response", file=sys.stderr)
                    # Best-effort unsubscribe before exiting
                    if do_subscribe:
                        try:
                            unsub = json.dumps({"pid": pid, "cmd": "unsubscribe"})
                            client.send_message(unsub)
                        except OSError:
                            pass
                    sys.exit(1)

            # ----------------------------------------------------------------
            # Unsubscribe
            # ----------------------------------------------------------------
            if do_subscribe:
                if use_tool_protocol:
                    unsub_msg = json.dumps({"pid": pid, "cmd": "unsubscribe"})
                else:
                    unsub_msg = json.dumps({"cmd": "UNSUBSCRIBE", "data": "", "pid": pid})
                _log(f"-> {unsub_msg}")
                try:
                    client.send_message(unsub_msg)
                except OSError:
                    # Server may have already exited (e.g. after "exit" command)
                    pass

            client.stop()

    except OSError as exc:
        print(f"cpipe: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\ncpipe: interrupted", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
