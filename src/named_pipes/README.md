# named_pipes

Top-level package for low-latency inter-process communication (IPC) via named pipes (FIFOs). Provides the public API, shared utilities, a service registry, and system introspection.

## Public API

`from named_pipes import ...`

| Symbol | Type | Description |
|---|---|---|
| `DataNamedPipe` | class | Binary IPC pipe |
| `TextNamedPipe` | class | JSON message IPC pipe |
| `ToolServer` | class | Named-pipe tool server |
| `ToolClient` | class | Named-pipe tool client |
| `Role` | enum | `SERVER` or `CLIENT` |
| `get_pids_for_pipe(path)` | function | PIDs that currently have `path` open |
| `get_version()` | function | Package version string (includes git commit for editable installs) |

## Modules

| Module | Description |
|---|---|
| [`pipes`](pipes/README.md) | Low-level FIFO transport (`DataNamedPipe`, `TextNamedPipe`) |
| [`tools`](tools/README.md) | Named Pipe Tools protocol (`ToolServer`, `ToolClient`) |
| [`interfaces`](interfaces/README.md) | Interface/schema definitions for commands and events |
| [`chat`](chat/README.md) | LLM chat inference server |
| [`tts`](tts/README.md) | Text-to-speech synthesis server |
| [`stt`](stt/README.md) | Speech-to-text transcription server |
| [`app`](app/README.md) | CLI (`cpipe`) and TUI dashboard |

## Key Files

### `registry.py`

Central catalogue of every backend, model, server type, and interface definition known to the package. Used by the TUI and CLI to enumerate what can be launched and discovered.

### `system.py`

Collects hardware and software environment info (CPU, GPU/MPS, RAM, installed ML libraries). Used by the TUI's Info tab and `get_state` responses.

### `utils.py`

Pipe-level utilities:

- `get_pids_for_pipe(path)` — scan open file descriptors via `psutil` to find which processes have a pipe open
- Pipe path construction and orphan detection helpers used by `cpipe --list` and `cpipe --clear`

## Protocol Overview

```
Client → Server  /tmp/tool-{name}           upstream FIFO  (JSON commands)
Server → Client  /tmp/tool-{name}-{pid}     downstream FIFO (JSON events)
```

The server creates the upstream FIFO. Each client creates its own per-PID downstream FIFO and announces itself with a `subscribe` command. All FIFOs are opened `O_RDWR` so neither end ever blocks or sees a spurious EOF.

See [`named-pipe-tools.md`](../../../named-pipe-tools.md) for the full protocol specification.
