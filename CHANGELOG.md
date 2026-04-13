# Changelog

## 0.1.1 — 2026-04-12

### New features

- **`cpipe` CLI** — command-line tool for discovering, inspecting, and sending commands to named-pipe servers (`--list`, `--pid`, `--clear` flags)
- **`TTSNamedPipe`** — real-time text-to-speech server over a named pipe, supporting mlx-audio (macOS) and vllm-omni (Linux)
- **`ChatNamedPipe`** — LLM chat server with streaming inference via `TextIteratorStreamer`; LLM tokens stream directly to a TTS server in real time
- **`ToolNamedPipe`** — named-pipe server variant for tool-calling workflows
- **Sender-targeted routing** — PID is threaded through all pipe classes (`TextNamedPipe`, `DataNamedPipe`, `BasicPipeChannel`, `ChatNamedPipe`) so handlers can route replies back to a specific client
- **Pipe scanning** — fast `O_WRONLY` probe + `lsof`-based PID lookup to detect and clear orphaned pipes under `/tmp`
- **Streaming timeout fix** — response timeout is suspended once streaming begins so long LLM outputs don't time out mid-stream

### Improvements

- Refactored `PipeChannel` into `TextNamedPipe` / `DataNamedPipe` hierarchy with cleaner multiple-inheritance support
- Idempotent `close()` guards and destructor to prevent double-close errors
- Skill/help text auto-loaded from `SKILL.md` in the caller's directory
- `subscribe` / `unsubscribe` added to `BasicPipeChannel`

### Infrastructure

- GitHub Actions workflows for Ruff lint, CSharpier format, and Python tests
- PyPI publish workflow via OIDC trusted publisher (triggers on GitHub release)

## 0.1.0 — initial release

- Four-pipe IPC protocol (`cmd-upstream`, `cmd-downstream`, `data-upstream`, `data-downstream`)
- `BasicPipeChannel` with decorator-based command handlers (`@ch.handler("CMD")`)
- C# `PipeChannel` client with background listener threads and `MessageReceived` / `DataReceived` events
- `PING`, `GREET`, `TIME`, `ECHO`, `SEND_BYTES`, `QUIT` built-in commands
- `psutil`-based `get_pids_for_pipe()` utility
