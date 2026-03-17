# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A proof-of-concept for low-latency interprocess communication (IPC) via named pipes between a Python server and a C# (.NET 10) client. The goal is lower latency than local HTTP for agent/service communication.

## Commands

### Python server
```bash
python main.py   # Start the Python server (creates pipes, listens for messages)
```

### C# client
```bash
dotnet build            # Build the C# client
dotnet run              # Run the C# client (requires Python server to be running first)
```

**Startup order matters:** The Python server (`main.py`) must be started before the C# client (`dotnet run`), because Python creates the FIFO files and C# opens them.

## Architecture

Four named pipes carry traffic between the processes. Paths are derived from a `pipe_name` parameter (default `/tmp/agent`):

| Pipe path | Direction | Format |
|---|---|---|
| `<pipe_name>-upstream-cmd` | C# → Python | Newline-delimited JSON `{"cmd": "...", "data": "..."}` |
| `<pipe_name>-downstream-cmd` | Python → C# | Same |
| `<pipe_name>-upstream-data` | C# → Python | 4-byte big-endian length prefix + raw bytes |
| `<pipe_name>-downstream-data` | Python → C# | Same |

All four FIFOs are opened `O_RDWR` on the Python side so the open calls never block and the read end never sees EOF when the remote writer closes its side.

### Python side (`pipe_reader.py`, `main.py`, `utils.py`)
- `pipe_reader.py`: `PipeChannel` class manages all four pipes as a context manager. `ch.handler("CMD")` is a decorator that registers handler functions. `ch.dispatch()` routes incoming messages to handlers.
- `main.py`: registers handlers via `@ch.handler(...)` and runs the blocking read loop.
- `utils.py`: `get_pids_for_pipe()` uses `psutil` to find which PIDs have a pipe path open — useful for debugging.

### C# side (`PipeChannel.cs`, `Program.cs`)
- `PipeChannel` wraps the four `FileStream`s with separate background listener threads (`MsgListener`, `DataListener`) for non-blocking receives.
- Events `MessageReceived` and `DataReceived` fire on their respective listener threads — handlers must be thread-safe.
- `Program.cs` drives a sequential command chain via a `Queue<Action>`, dispatching the next step from inside each `MessageReceived` handler.

### Supported commands
`PING` → `PONG`, `GREET`, `TIME`, `ECHO`, `SEND_BYTES` (sends data on the data pipe and echoes it back), `QUIT` → `BYE`

