# Documentation

Full architecture, API reference, protocol details, and design rationale for the named-pipes library.

## Table of contents

- [What are named pipes?](#what-are-named-pipes)
- [Why named pipes?](#why-named-pipes)
- [Why not CLI or MCP?](#why-not-cli-or-mcp)
- [Architecture](#architecture)
- [API reference](#api-reference)
  - [TextNamedPipe and DataNamedPipe](#textnamedpipe-and-datanamedpipe)
  - [ToolNamedPipe](#toolnamedpipe)
  - [ChatNamedPipe](#chatnamedpipe)
  - [TTSNamedPipe](#ttsnamedpipe)
  - [STTNamedPipe](#sttnamedpipe)
- [cpipe CLI reference](#cpipe-cli-reference)
- [Installation details](#installation-details)

---

## What are named pipes?

A named pipe (FIFO) is a special file in the filesystem that acts as a one-way channel between two processes: one process writes to it, the other reads from it. Unlike anonymous pipes (`|` in a shell), named pipes have a path on disk, so unrelated processes can open them by name without a parent–child relationship. On Linux and macOS they are created with `mkfifo` and live under `/tmp` (or anywhere else on the filesystem). Data flows through kernel memory — no disk I/O — making them fast and simple for same-machine IPC.

## Why named pipes?

- **Statefulness**: The tool runs as a persistent process with in-memory state, unlike a CLI that must reload state from disk or an API on every invocation.
- **Low latency**: Named pipes are the fastest IPC mechanism after shared memory — critical for real-time applications like voice agents.

## Why not CLI or MCP?

**CLI tools** spawn a new process on every invocation. They pay startup cost each time, must reload any state they need from disk, and exit when the call completes. For lightweight commands that is fine, but for capabilities like LLM inference, vector search, or browser automation — where the expensive part is loading model weights, building an index, or launching a browser — that per-call overhead is prohibitive. A named-pipe server starts once, holds everything in memory, and stays resident between calls. The orchestrator sends a message and gets a response; no process is spawned, no state is reloaded.

**MCP** is built around a different assumption: the model lives elsewhere (in the cloud, behind an API), and tools run as local or remote servers that the framework discovers and manages. That architecture introduces JSON-RPC framing, a process-spawning and discovery protocol, and a framework intermediary sitting between the model and the tool. For a self-hosted agent running entirely on one machine, all of that is overhead with no benefit. Named pipes skip the protocol layer entirely — the orchestrator opens a file path, writes a message, and reads the reply. The execution loop stays in the orchestrator's hands, with no framework in the middle and no network stack involved.

## Architecture

The library builds a hierarchy of abstractions over named pipes, from low-level I/O up to application-level protocols:

```
TextNamedPipe (ABC)   DataNamedPipe (ABC)
       ↓
ToolNamedPipe
    ↓       ↓       ↓
ChatNamedPipe  TTSNamedPipe  STTNamedPipe
```

### Pipe layout

Four named pipes carry traffic between a server and its clients. Paths are derived from a `pipe_name` parameter (e.g. `tool-chat` → `/tmp/tool-chat`):

| Pipe path | Direction | Format |
|---|---|---|
| `/tmp/<name>` | client → server | Newline-delimited JSON `{"cmd": "...", "data": "..."}` |
| `/tmp/<name>-<pid>` | server → client | Same (one pipe per subscribed client PID) |
| `/tmp/<name>-data` | client → server | 4-byte big-endian length prefix + raw bytes |
| `/tmp/<name>-data-<pid>` | server → client | Same |

All FIFOs are opened `O_RDWR` on the server side so `open()` never blocks and the read end never sees EOF when the remote writer closes.

---

## API reference

### TextNamedPipe and DataNamedPipe

These are the two abstract base classes. All higher-level protocols are built on top of one or both of them.

**`TextNamedPipe`** manages a pair of named pipes for JSON message exchange:
- Upstream pipe (`/tmp/<name>`) — shared; all clients write here
- Downstream pipe (`/tmp/<name>-<pid>`) — one per subscribed client; the server writes here

Each client subscribes with its PID, and the server creates a dedicated downstream pipe for it. This allows one server to handle multiple concurrent clients, routing responses back to the correct client. Subclasses implement `msg_handler_fn(msg: dict)` to define message handling logic.

**`DataNamedPipe`** provides the same multiplexing model for binary data, using a 4-byte big-endian length prefix to frame each payload. Subclasses implement `data_handler_fn(data: bytes)`.

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

See [`src/ex_tts_pipe/`](src/ex_tts_pipe/) for the server and an LLM→TTS pipeline client that streams tokens directly into the TTS server.

### STTNamedPipe

`STTNamedPipe` inherits from `ToolNamedPipe` and implements a real-time speech-to-text tool. On construction it starts a background thread that captures the default microphone and runs streaming decode via a vendored [Voxtral](https://mistral.ai/news/voxtral) implementation. Transcribed tokens and VAD lifecycle events are broadcast to all subscribers as JSON messages.

Backend: vendored Voxtral (`mlx-community/Voxtral-Mini-4B-Realtime-6bit`, macOS / Apple Silicon).

Broadcast messages (no custom commands — this is a producer-only server):

| Message | Description |
|---------|-------------|
| `{"result": "<token>"}` | Transcribed token chunk |
| `{"event": "speech_start"}` | VAD detected speech onset |
| `{"event": "speech_end"}` | VAD detected end of speech |

```python
from named_pipes.stt import STTNamedPipe

with STTNamedPipe("stt") as ch:
    done = ch.listen()
    print("STT server listening on /tmp/tool-stt ...")
    done.wait()
```

See [`src/ex_stt_pipe/`](src/ex_stt_pipe/) for a working server and a minimal subscriber client.

---

## cpipe CLI reference

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

For the Claude Code skill that teaches the assistant to use `cpipe`, see [`.claude/skills/named-pipe-tools/SKILL.md`](.claude/skills/named-pipe-tools/SKILL.md).

---

## Installation details

```bash
pip install -e .            # core library only
pip install -e ".[llm]"     # LLM inference support
pip install -e ".[tts]"     # TTS (macOS: mlx-audio + sounddevice)
pip install -e ".[stt]"     # STT (sounddevice; Voxtral weights vendored)
pip install -e ".[kokoro]"  # Kokoro phonemiser (English misaki frontend)
pip install -e ".[dev]"     # dev tools
```

**Platform-specific dependencies:**

| Extra | macOS | Linux |
|-------|-------|-------|
| `[llm]` | `mlx-lm`, `transformers>=5.5.0`, `torch` | `vllm`, `transformers>=5.5.0`, `torch` |
| `[tts]` | `mlx-audio`, `sounddevice` | — |
| `[stt]` | `sounddevice` (Voxtral vendored under `named_pipes/stt/voxtral/`) | — |
