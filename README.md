# named-pipes

Low-latency interprocess communication via named pipes — lower overhead than local HTTP, simpler than shared memory.

Built as a foundation for agent/service architectures where a Python orchestrator talks to multiple specialized servers (LLM inference, STT, TTS, vector DBs, etc.) on the same machine.

## Installation

```bash
# Core library only
pip install -e .

# With LLM inference support
pip install -e ".[llm]"

# With dev tools
pip install -e ".[dev]"
```

Requires Python 3.11+. LLM extras: `vllm`, `transformers>=5.5.0`, `torch`.

## Overview

The library builds a hierarchy of abstractions over named pipes, from low-level I/O up to application-level protocols:

```
TextNamedPipe (ABC)       DataNamedPipe (ABC)
       ↓              ↘          ↓
ToolNamedPipe          BasicPipeChannel (text + data)
       ↓
ChatNamedPipe
```

### Why Named Pipes?

- **Statefulness**: The tool runs as a persistent process with in-memory state, unlike a CLI that must reload state from disk or an API on every invocation.
- **Low latency**: Named pipes are the fastest IPC mechanism after shared memory — critical for real-time applications like voice agents.

**Example tools**: LLM inference server, STT/TTS streaming server, in-memory key-value store, vector database, browser automation server.

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

`ChatNamedPipe` inherits from `ToolNamedPipe` and implements an LLM inference tool. It registers a `chat` command that accepts an OpenAI-style message list and returns the assistant's reply. Two backends are supported:

- **`Backend.TRANSFORMERS`** — HuggingFace Transformers; device is auto-detected (MPS / CUDA / CPU)
- **`Backend.VLLM`** — vLLM for higher-throughput serving

```python
from named_pipes.chat_named_pipe import Backend, ChatNamedPipe

with ChatNamedPipe(
    "llm",
    "Qwen/Qwen3.5-0.8B",
    backend=Backend.TRANSFORMERS,
    description="Simple LLM chat server powered by Qwen3.5-0.8B.",
    max_new_tokens=256,
    do_sample=False,
) as ch:
    done = ch.listen()
    print("LLM server listening on /tmp/tool-llm ...")
    done.wait()
```

See [`src/ex_chat_pipe/`](src/ex_chat_pipe/) for a working client/server example.

## Running the examples

**Start order matters:** the server creates the named pipes; the client opens them.

```bash
# LLM server (Terminal 1)
conda activate named-pipes
python src/ex_chat_pipe/server.py

# LLM client (Terminal 2)
conda activate named-pipes
python src/ex_chat_pipe/client.py
```

```bash
# BasicPipeChannel (Terminal 1)
conda activate named-pipes
python src/ex_basic_pipe/server.py

# BasicPipeChannel client (Terminal 2)
conda activate named-pipes
python src/ex_basic_pipe/client.py
```
