<div align="center">
<img src="MascotAnimation.gif" width="100%"></img>
</div>

# Named Pipes as Agentic Tools

**This library uses named pipes as the transport layer for agentic tool servers — persistent background processes that expose capabilities such as LLM inference, text-to-speech, vector search, or browser automation to a Python orchestrator running on the same machine.**

Because named pipes route data through kernel memory rather than a network stack, they offer lower latency than local HTTP and far less complexity than shared memory, making them a practical sweet spot for real-time applications like voice agents. Unlike MCP, which is designed for tool calls from a remote or cloud-hosted model and carries the overhead of JSON-RPC over stdio or SSE, named pipes are a purely local, binary-capable channel that keeps the orchestrator fully in control of the execution loop — no server discovery protocol, no process spawning by the framework, and no round-trip through an intermediary.

Each tool server stays resident between calls, so it holds model weights, database indexes, or browser state in memory rather than reloading them on every request. A thin client-side abstraction handles the subscribe/send/receive/unsubscribe lifecycle, and a `cpipe` command-line utility lets you send ad-hoc commands to any running server from the terminal.

The same servers can also be driven directly from Claude Code or another agentic coding tool. An included agent skill teaches the assistant how to discover running pipe servers with `cpipe --list`, inspect their capabilities, and send commands — so the LLM can query a local inference server or trigger TTS playback without leaving the coding session.

## What are named pipes?

A named pipe (FIFO) is a special file in the filesystem that acts as a one-way channel between two processes: one process writes to it, the other reads from it. Unlike anonymous pipes (`|` in a shell), named pipes have a path on disk, so unrelated processes can open them by name without a parent–child relationship. On Linux and macOS they are created with `mkfifo` and live under `/tmp` (or anywhere else on the filesystem). Data flows through kernel memory — no disk I/O — making them fast and simple for same-machine IPC.

## Why named pipes?

- **Statefulness**: The tool runs as a persistent process with in-memory state, unlike a CLI that must reload state from disk or an API on every invocation.
- **Low latency**: Named pipes are the fastest IPC mechanism after shared memory — critical for real-time applications like voice agents.

## Example tools
- LLM inference server
- STT/TTS streaming server
- in-memory key-value store
- vector/graph database
- browser automation server.

## Installation

```bash
# Core library only
pip install -e .

# With LLM inference support
pip install -e ".[llm]"

# With TTS support (macOS: mlx-audio + sounddevice)
pip install -e ".[tts]"

# With Kokoro phonemiser (English misaki frontend)
pip install -e ".[kokoro]"

# With dev tools
pip install -e ".[dev]"
```

Requires Python 3.11+. LLM extras (macOS): `mlx-lm`, `transformers>=5.5.0`, `torch`. LLM extras (Linux): `vllm`, `transformers>=5.5.0`, `torch`. TTS extras (macOS): `mlx-audio`, `sounddevice`.

## Overview

The library builds a hierarchy of abstractions over named pipes, from low-level I/O up to application-level protocols:

```
TextNamedPipe (ABC)       DataNamedPipe (ABC)
       ↓              ↘          ↓
ToolNamedPipe          BasicPipeChannel (text + data)
       ↓         ↘
ChatNamedPipe   TTSNamedPipe
```

### TextNamedPipe and DataNamedPipe

These are the two abstract base classes. All higher-level protocols are built on top of one or both of them.

**`TextNamedPipe`** manages a pair of named pipes for JSON message exchange:
- Upstream pipe (`/tmp/<name>`) — shared; all clients write here
- Downstream pipe (`/tmp/<name>-<pid>`) — one per subscribed client; the server writes here

Each client subscribes with its PID, and the server creates a dedicated downstream pipe for it. This allows one server to handle multiple concurrent clients, routing responses back to the correct client. Subclasses implement `msg_handler_fn(msg: dict)` to define message handling logic.

**`DataNamedPipe`** provides the same multiplexing model for binary data, using a 4-byte big-endian length prefix to frame each payload. Subclasses implement `data_handler_fn(data: bytes)`.

All named pipes are opened `O_RDWR` on the server side so `open()` never blocks and the read end never sees EOF when the remote writer closes.

### BasicPipeChannel

`BasicPipeChannel` is a concrete implementation that combines both `TextNamedPipe` and `DataNamedPipe`, illustrating how the two base classes can be composed into a single channel. It exposes a simple decorator-based API for registering handlers:

```python
with BasicPipeChannel(role=Role.SERVER) as ch:
    @ch.handler("PING")
    def on_ping(data: str):
        ch.send_message("PONG", "")

    @ch.data_handler
    def on_data(data: bytes):
        ch.send_data(data)  # echo

    ch.listen().wait()
```

See [`src/ex_basic_pipe/`](src/ex_basic_pipe/) for a working client/server example.

### ToolNamedPipe

`ToolNamedPipe` extends `TextNamedPipe` with a standardized protocol for building **agentic tools** — persistent server processes that expose capabilities to one or more clients (e.g. an agent). It defines a set of built-in commands (`subscribe`, `unsubscribe`, `description`, `help`, `exit`) and allows tools to register custom commands via a decorator.

The full protocol specification is in [`named-pipe-tools.md`](named-pipe-tools.md).

### ChatNamedPipe

`ChatNamedPipe` inherits from `ToolNamedPipe` and implements an LLM inference tool. It registers two commands:

- **`chat`** — streaming inference; sends token chunks as they are generated, followed by a `done: true` sentinel
- **`chat_blocking`** — non-streaming inference; returns the full reply in one message

Two backends are supported:

- **`Backend.TRANSFORMERS`** — HuggingFace Transformers with `TextIteratorStreamer`; device is auto-detected (MPS / CUDA / CPU)
- **`Backend.VLLM`** — vLLM for higher-throughput serving (Linux)

```python
from named_pipes.chat_named_pipe import Backend, ChatNamedPipe

with ChatNamedPipe(
    "chat",
    "Qwen/Qwen3.5-0.8B",
    backend=Backend.TRANSFORMERS,
    description="Simple LLM chat server powered by Qwen3.5-0.8B.",
    max_new_tokens=256,
    do_sample=False,
) as ch:
    done = ch.listen()
    print("LLM server listening on /tmp/tool-chat ...")
    done.wait()
```

See [`src/ex_chat_pipe/`](src/ex_chat_pipe/) for a working client/server example.

### TTSNamedPipe

`TTSNamedPipe` inherits from `ToolNamedPipe` and implements a real-time text-to-speech tool. It accumulates incoming text tokens, splits on sentence boundaries (`. ! ?`), and synthesises each sentence as audio played through the system speakers. Synthesis and playback run on background threads so the pipe stays responsive during generation.

Backend: [mlx-audio](https://github.com/Blaizzy/mlx-audio) with the Kokoro-82M model (macOS / Apple Silicon).

Commands (in addition to `ToolNamedPipe` builtins):

| Command | Data | Description |
|---------|------|-------------|
| `text` | token string | Append tokens to the text buffer; flush automatically at sentence boundaries |
| `flush` | — | Force-synthesise whatever remains in the buffer (call at end of generation) |

```python
from named_pipes.tts_named_pipe import TTSNamedPipe

with TTSNamedPipe("tts") as ch:
    done = ch.listen()
    print("TTS server listening on /tmp/tool-tts ...")
    done.wait()
```

See [`src/ex_tts_pipe/`](src/ex_tts_pipe/) for a working server example and [`src/ex_tts_pipe/`](src/ex_tts_pipe/client.py) for the LLM→TTS pipeline client that streams LLM tokens directly into the TTS server in real time.

## cpipe — CLI for named-pipe servers

`cpipe` is installed as a console script and lets you send commands to any named-pipe tool server from the terminal, like `curl` for pipes.

```bash
# Send a command (subscribe → send → wait for response → unsubscribe)
cpipe /tmp/tool-chat chat --data '{"messages": [{"role":"user","content":"Hello"}]}'

# Discover running pipe servers
cpipe --list            # connected / orphaned pipes under /tmp
cpipe --pid             # same, plus the PIDs that have each pipe open
cpipe --clear           # delete orphaned (no process has open) pipes

# Options
cpipe --timeout 30      # seconds to wait for response (default: 10)
cpipe --no-subscribe    # skip subscribe/unsubscribe handshake
cpipe --no-wait         # fire and forget
cpipe -v                # verbose: print sent/received messages to stderr
```

See [`.claude/skills/named-pipe-tools/SKILL.md`](.claude/skills/named-pipe-tools/SKILL.md) for the skill that teaches Claude Code how to use `cpipe` to interact with live servers.

## Running the examples

**Start order matters:** the server creates the named pipes; the client opens them.

```bash
# LLM server (Terminal 1)
conda activate named-pipes
python src/ex_chat_pipe/server.py

# LLM client — streaming + blocking demo (Terminal 2)
conda activate named-pipes
python src/ex_chat_pipe/client.py
```

```bash
# LLM→TTS pipeline (three terminals)
conda activate named-pipes
python src/ex_chat_pipe/server.py   # Terminal 1: LLM server  (/tmp/tool-chat)
python src/ex_tts_pipe/server.py    # Terminal 2: TTS server  (/tmp/tool-tts)
python src/ex_tts_pipe/client.py    # Terminal 3: pipeline client (streams LLM tokens → TTS)
```

```bash
# BasicPipeChannel (Terminal 1)
conda activate named-pipes
python src/ex_basic_pipe/server.py

# BasicPipeChannel client (Terminal 2)
conda activate named-pipes
python src/ex_basic_pipe/client.py
```
