# Changelog

## 0.5.0 — 2026-06-21

### New features

- **C# `ToolClient`** — .NET client mirroring `tool_client.py`: creates the per-PID downstream FIFO via P/Invoke `mkfifo`, opens both FIFOs `O_RDWR`, and runs a background listener thread; `Program.cs` demo exercises `ping`, `get_state`, `get_description`, and a custom `greet` command
- **Textual TUI (`named_pipes.app`)** — full terminal app with a Tools panel (live state/health polling), a Launcher modal for Chat/TTS/STT with per-backend config forms, a Messenger for sending commands/viewing streamed events and stdout logs, and an Info modal
- **Interface system (`named_pipes.interfaces`)** — `Interface`/`CommandSpec`/`EventSpec`/`ArgSpec` describe each server's commands and events; new `list_interfaces`/`get_interface` built-in commands and an `INTERFACES` registry drive the Messenger's interface-aware command UI (arg defaults, caching, type coercion)
- **`SystemInfo`** — platform-aware system info module, displayed in the TUI
- **Model/backend registry** — unified `Backend` enum and `BackendEntry` registry for selecting platform-specific chat backends and default models from the Launcher
- **STT interface expanded** — `start`/`pause`/`list_devices`/`get_device`/`set_device` commands, with `speech`/`devices`/`device` response/update events, implemented by both the Voxtral-backed `STTServer` (`server.py`) and an alternate Moonshine Voice backend (`server_moonshine.py`); microphone/model loading is now deferred until `start` is received

### Improvements

- Voxtral's `stream_transcribe` gained a `device` parameter, threaded through to `sounddevice.InputStream`, so `set_device` actually selects the input device
- Fixed an event-ordering bug where `state_changed("listening")` was broadcast before `speech_end`, leaving client transcript lines unterminated
- Promoted the STT test client into `src/examples/stt_client.py`: lists/selects an input device interactively before starting transcription, replacing the old producer-only example
- Numerous TUI layout/styling fixes: panel borders and separator junctions, scrollbar suppression on `AutoTextArea`, Commands/stdout panel sizing and padding, stable tool-selection highlighting, `ListView` replacing `DataTable` in the Tools panel

### Infrastructure / Documentation

- Reorganised `named_pipes` into `named_pipes.pipes`, `named_pipes.tools`, and `named_pipes.app` packages; `cpipe` moved into `named_pipes.app.cli`
- `SKILL.md` renamed to `HELP.md` across all tool packages
- Added CC-BY-SA-4.0 copyright headers to all Python files
- Added `moonshine-voice` to the `stt` extras

## 0.4.0 — 2026-04-20

### New features

- **`state_changed` handler in `stt_client`** — `_STTClient` now prints server state transitions (`[state_changed] <state>`) as they arrive
- **`speech_start` / `speech_end` events in `TTSServer`** — server broadcasts these events at the boundaries of each synthesis pass; `tts_client` handles them
- **KokoroPipeline warm-up** — `TTSServer` now pre-warms the Kokoro pipeline during `__init__`, reducing first-synthesis latency

### Improvements

- **`@self.on()` decorator in clients** — `stt_client`, `tts_client`, and `chat_client` all migrated from `on_message` callbacks to the `@self.on()` decorator pattern introduced in `ToolClient`
- **`--verbose` flag forwarding** — `cpipe --serve` now correctly passes the `--verbose` flag through to the server config
- **Error event documentation** — protocol spec now documents the `error` event emitted for unknown commands

## 0.3.1 — 2026-04-19

### New features

- **`cpipe --version`** — prints the installed package version; on editable installs, appends git commit info when not on a tagged commit (e.g. `0.3.0-3-gabcdef`)
- **`get_version()`** — new public helper in `named_pipes.utils` (and re-exported from `named_pipes`) that implements the version-resolution logic above

## 0.3.0 — 2026-04-17

### New features

- **`STTState` enum** — `STTServer` now tracks lifecycle state: `loading` (models loading), `listening` (waiting for speech), `transcribing` (speech detected, decoding tokens), `error`
- **`TTSState` enum** — `TTSServer` now tracks lifecycle state: `loading` (model loading), `idle` (queue empty), `synthesizing` (generating audio for a sentence), `error`
- **`verbose` flag** — `ChatConfig`, `STTConfig`, and `TTSConfig` each gain a `verbose: bool = False` field; when enabled, servers print inference output and progress to stdout

### Improvements

- **Handler refactor** — `ChatServer` and `ToolServer` built-in handlers moved from inline closures to named methods (`_handle_chat`, `_handle_chat_blocking`, `_register_builtin_handlers`), making them independently testable
- **`on_ready` callback** — `stream_transcribe` now accepts an optional `on_ready` callback invoked after both the Voxtral ASR model and Silero VAD finish loading, used by `STTServer` to transition from `loading` to `listening`
- **`state_changed` broadcasts** — all three concrete servers (`chat`, `stt`, `tts`) now broadcast `{"event": "state_changed", "state": "<value>"}` to subscribers on every state transition

### Infrastructure / Documentation

- **Protocol spec** (`named-pipe-tools.md`) — new "Tool State" section documenting the `state_changed` broadcast, base states, and extended states for all three tools
- **Tool READMEs** (`chat`, `stt`, `tts`) — each README now includes a States section describing valid state values and when each occurs

## 0.2.0 — 2026-04-16

### New features

- **`ping` command** — built-in health check on every `ToolServer` server; responds with `"pong"`
- **`status` command** — built-in state query; responds with the server's current `ToolState` value (e.g. `"running"`)
- **`ToolState` enum** — `ToolServer` now tracks its lifecycle state via a `_state` field; base state is `RUNNING`

### Improvements

- `cpipe --list`, `--pid`, `--clear` now filter to `tool-*` pipes only, ignoring unrelated FIFOs under `/tmp`
- `cpipe --pid` prints a progress message before the slow process scan
- `ToolServer` loads `SKILL.md` via the concrete subclass's module file (fixes `cpipe chat help` returning wrong content when launched via `cpipe --serve`)
- Restructured chat and TTS servers into subpackages (`named_pipes/chat/`, `named_pipes/tts/`) matching the STT layout
- Removed `BasicPipeChannel` and legacy example scripts; `cpipe` and docs updated to reflect `ToolServer`-only scope

### Infrastructure / Documentation

- Added `README.md` for chat, STT, and TTS servers covering startup, commands, and `cpipe` examples
- `ping` and `status` documented in protocol spec (`named-pipe-tools.md`), all `SKILL.md` files, and server READMEs
- Fixed CI dependency install (`--no-deps` dropped; now installs via `.[dev]` to include `pydantic`)

## 0.1.2 — 2026-04-16

### New features

- **`STTServer`** — real-time speech-to-text server over a named pipe; captures the default microphone and streams transcribed tokens and VAD lifecycle events (`speech_start`, `speech_end`) to all subscribers
- **Voxtral backend** — Voxtral Mini 4B Realtime (6-bit) vendored under `named_pipes/stt/voxtral/`; switched from Whisper to Voxtral Realtime with progressive token streaming
- **Silero VAD** — replaced RMS silence detection with Silero VAD for more accurate speech onset/end detection
- **STT callbacks** — `on_token`, `on_speech_start`, `on_speech_end` callbacks and a `stop_event` for clean shutdown of the transcription thread
- **`ex_stt_pipe` example** — server and subscriber client demonstrating STT broadcast

### Improvements

- Parallelised STT partial transcriptions via `ThreadPoolExecutor`
- `STT` optional dependency group added to `pyproject.toml`

### Infrastructure

- Switched CI from pip to `uv`; fixed mlx test skipping on Linux, ruff invocation via `uvx`, and vllm resolution in the pytest step

### Documentation

- Rewrote `README.md` following a highlights-first structure; moved detailed architecture, API reference, and design rationale into a new `DOCS.md`
- Added `SKILL.md` files for the chat and TTS servers (loaded from the caller's directory)

## 0.1.1 — 2026-04-12

### New features

- **`cpipe` CLI** — command-line tool for discovering, inspecting, and sending commands to named-pipe servers (`--list`, `--pid`, `--clear` flags)
- **`TTSServer`** — real-time text-to-speech server over a named pipe, supporting mlx-audio (macOS) and vllm-omni (Linux)
- **`ChatServer`** — LLM chat server with streaming inference via `TextIteratorStreamer`; LLM tokens stream directly to a TTS server in real time
- **`ToolServer`** — named-pipe server variant for tool-calling workflows
- **Sender-targeted routing** — PID is threaded through all pipe classes (`TextNamedPipe`, `DataNamedPipe`, `BasicPipeChannel`, `ChatServer`) so handlers can route replies back to a specific client
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
