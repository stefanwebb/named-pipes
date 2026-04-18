<div align="center">
<img src="https://raw.githubusercontent.com/stefanwebb/named-pipes/main/MascotAnimation.gif" width="75%"></img>
</div>

<h1 align="center">Named Pipes as Agentic Tools</h1>

<p align="center">
Low-latency IPC for persistent AI tool servers — LLM inference, TTS, STT, vector search, and more — all on one machine, no network stack required.
</p>

---

## ✨ Highlights

- **Persistent servers** — model weights and state stay loaded between calls; no per-request startup cost
- **Kernel-speed IPC** — named pipes route through kernel memory, not a network stack; lower latency than local HTTP
- **Multi-client fanout** — one server handles many concurrent clients; each gets its own downstream pipe
- **Decorator API** — register command handlers with a single `@ch.handler("CMD")` line
- **`cpipe` CLI** — send ad-hoc commands to any running server from the terminal, like `curl` for pipes
- **Claude Code skill** — an included skill teaches the assistant to discover and query live servers without leaving the session
- **Ready-made servers** — drop-in pipes for LLM chat, text-to-speech, and speech-to-text

## Overview

This library uses named pipes as the transport layer for **agentic tool servers** — persistent background processes that expose capabilities such as LLM inference, text-to-speech, vector search, or browser automation to a Python orchestrator running on the same machine.

Because named pipes route data through kernel memory rather than a network stack, they offer lower latency than local HTTP and far less complexity than shared memory — a practical sweet spot for real-time applications like voice agents.

The same servers can be driven directly from Claude Code. An included agent skill teaches the assistant how to discover running pipe servers with `cpipe --list`, inspect their capabilities, and send commands.

For a deeper look at the design decisions and API reference, see [DOCS.md](DOCS.md).

## Installation

```bash
# Core library only
pip install -e .

# With LLM inference support
pip install -e ".[llm]"

# With TTS support (macOS: mlx-audio + sounddevice)
pip install -e ".[tts]"

# With STT support (sounddevice; Voxtral weights vendored)
pip install -e ".[stt]"
```

Requires **Python 3.11+**. See [DOCS.md](DOCS.md) for platform-specific dependency details.

## Quick start

**1. Start a server** (Terminal 1):

```bash
conda activate named-pipes
cpipe --serve chat   # LLM server on /tmp/tool-chat
```

**2. Query it from the CLI** (Terminal 2):

```bash
cpipe /tmp/tool-chat chat --data '{"messages": [{"role":"user","content":"Hello!"}]}'
```

**3. Or write a client in Python:**

```python
from named_pipes.tool_named_pipe import ToolNamedPipe, Role

with ToolNamedPipe("tool-chat", role=Role.CLIENT) as ch:
    ch.send_message("chat", '{"messages": [{"role":"user","content":"Hello!"}]}')
    for msg in ch.receive_stream():
        print(msg)
```

## Examples

Start order matters — **server first**, then client (server creates the FIFOs).

```bash
# LLM chat
cpipe --serve chat                  # Terminal 1
python src/ex_chat_pipe/client.py   # Terminal 2

# LLM → TTS pipeline (spoken output)
cpipe --serve chat                  # Terminal 1: LLM  (/tmp/tool-chat)
cpipe --serve tts                   # Terminal 2: TTS  (/tmp/tool-tts)
python src/ex_tts_pipe/client.py    # Terminal 3: pipeline client

# Speech-to-text
cpipe --serve stt                   # Terminal 1: STT  (/tmp/tool-stt)
python src/ex_stt_pipe/client.py    # Terminal 2: subscriber

```

## `cpipe` — CLI tool

```bash
cpipe /tmp/tool-chat chat --data '{"messages": [{"role":"user","content":"Hello"}]}'

cpipe --list    # discover running ToolNamedPipe servers (tool-* pipes)
cpipe --pid     # same, plus PIDs that have each pipe open
cpipe --clear   # delete orphaned tool pipes
```

See [DOCS.md](DOCS.md) for all options and the full protocol reference.

## Claude Code skill

An included skill at [`.claude/skills/cpipe/SKILL.md`](.claude/skills/cpipe/SKILL.md) teaches Claude Code how to use `cpipe` to discover, inspect, and interact with live servers — so the LLM can query a local inference server or trigger TTS playback without leaving the coding session.

## Resources

- [DOCS.md](DOCS.md) — architecture, API reference, protocol spec, and design rationale
- [`named-pipe-tools.md`](named-pipe-tools.md) — `ToolNamedPipe` protocol specification
- [`src/ex_chat_pipe/`](src/ex_chat_pipe/) — LLM chat example
- [`src/ex_tts_pipe/`](src/ex_tts_pipe/) — TTS example
- [`src/ex_stt_pipe/`](src/ex_stt_pipe/) — STT example
