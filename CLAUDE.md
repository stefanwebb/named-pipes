# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A proof-of-concept for low-latency interprocess communication (IPC) via named pipes between a Python server and a C# (.NET 10) client. The goal is lower latency than local HTTP for agent/service communication.

## Commands

### Named Pipe Tools demo (ToolServer + ToolClient)

```bash
# Terminal 1 — start the Python demo server
python src/examples/demo_server.py

# Terminal 2 — run the C# ToolClient demo (auto-launches server if not running)
cd src/MyClientConsole && dotnet run
```

**Startup order matters:** the Python server creates the upstream FIFO
(`/tmp/tool-demo`) before the C# client opens it.  The C# `Program.cs` will
wait up to 5 s for the pipe to appear, so launching both simultaneously works.

### Legacy PipeChannel demo

```bash
python src/my_server_console/main.py   # Start the legacy Python server
cd src/MyClientConsole && dotnet run   # Run the legacy C# client
```

## Architecture

### Named Pipe Tools protocol (current)

Each tool exposes two named pipes:

| Pipe path | Direction | Format |
|---|---|---|
| `/tmp/tool-{name}` | client → server | Newline-delimited JSON `{"pid": ..., "cmd": "...", ...}` |
| `/tmp/tool-{name}-{pid}` | server → client | Newline-delimited JSON `{"event": "...", ...}` |

The server creates the upstream FIFO.  Each client creates its own downstream
FIFO, which the server opens after receiving a `subscribe` command.

All FIFOs are opened `O_RDWR` (using `FileAccess.ReadWrite` in C#) so open
calls never block and the read end never sees EOF when the remote writer closes.

See `named-pipe-tools.md` for the full protocol specification.

#### Python side (`src/named_pipes/`)
- `tool_server.py`: `ToolServer` base class — listens on `/tmp/tool-{name}`.  Register custom commands with `@server.handler("cmd")`.  Built-in: `subscribe`, `unsubscribe`, `ping`, `get_state`, `get_description`, `get_help`, `get_config`, `stop`.
- `tool_client.py`: `ToolClient` base class — creates the per-PID downstream FIFO and subscribes.  Register event handlers with `@client.on("event")`.
- `text_named_pipe.py`: shared transport layer (`TextNamedPipe`), role-based pipe management, background listener thread with `select`.
- `utils.py`: `get_pids_for_pipe()` uses `psutil` to find which PIDs have a pipe path open.

#### C# side (`src/MyClientConsole/`)
- `ToolClient.cs`: mirrors `tool_client.py`.  Creates `/tmp/tool-{name}-{pid}` via `mkfifo` P/Invoke, opens both FIFOs `O_RDWR`, runs a background `ToolClientListener` thread.  Register handlers with `On("event", handler)`.  Call `StartListening()`, then `Subscribe()` before sending commands.
- `Program.cs`: demo that optionally launches `src/examples/demo_server.py`, then exercises `ping`, `get_state`, `get_description`, a custom `greet` command, and `stop`.

### Legacy PipeChannel protocol

Four named pipes derived from a `pipe_name` parameter (default `/tmp/agent`):

| Pipe path | Direction | Format |
|---|---|---|
| `<pipe_name>-cmd-upstream` | C# → Python | Newline-delimited JSON `{"cmd": "...", "data": "..."}` |
| `<pipe_name>-cmd-downstream` | Python → C# | Same |
| `<pipe_name>-data-upstream` | C# → Python | 4-byte big-endian length prefix + raw bytes |
| `<pipe_name>-data-downstream` | Python → C# | Same |

- `PipeChannel.cs`: wraps the four `FileStream`s with `MsgListener` and `DataListener` background threads.  `MessageReceived` and `DataReceived` events fire on listener threads — handlers must be thread-safe.

