"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

Demo tool server for testing the C# ToolClient.

Start this server, then run the C# client:
    python src/examples/demo_server.py
    cd src/MyClientConsole && dotnet run

The C# client will connect, exercise standard and custom commands, then
send stop to shut the server down.
"""

from named_pipes import ToolServer


def main():
    with ToolServer(
        "demo", description="Minimal demo server for C# ToolClient testing"
    ) as server:

        @server.handler("greet")
        def _(msg, pid):
            name = msg.get("name", "World")
            server.send_event("greeting", pid, message=f"Hello, {name}!")

        done = server.listen()
        print("Demo server listening on /tmp/tool-demo ...")
        done.wait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down.")
