## New features

- **C# `ToolClient`** — .NET client mirroring `tool_client.py`: creates the per-PID downstream FIFO via P/Invoke `mkfifo`, opens both FIFOs `O_RDWR`, and runs a background listener thread; `Program.cs` demo exercises `ping`, `get_state`, `get_description`, and a custom `greet` command
- **Textual TUI (`named_pipes.app`)** — full terminal app with a Tools panel (live state/health polling), a Launcher modal for Chat/TTS/STT with per-backend config forms, a Messenger for sending commands/viewing streamed events and stdout logs, and an Info modal
- **Interface system (`named_pipes.interfaces`)** — `Interface`/`CommandSpec`/`EventSpec`/`ArgSpec` describe each server's commands and events; new `list_interfaces`/`get_interface` built-in commands and an `INTERFACES` registry drive the Messenger's interface-aware command UI (arg defaults, caching, type coercion)
- **`SystemInfo`** — platform-aware system info module, displayed in the TUI
- **Model/backend registry** — unified `Backend` enum and `BackendEntry` registry for selecting platform-specific chat backends and default models from the Launcher
- **STT interface expanded** — `start`/`pause`/`list_devices`/`get_device`/`set_device` commands, with `speech`/`devices`/`device` response/update events, implemented by both the Voxtral-backed `STTServer` (`server.py`) and an alternate Moonshine Voice backend (`server_moonshine.py`); microphone/model loading is now deferred until `start` is received

## Improvements

- Voxtral's `stream_transcribe` gained a `device` parameter, threaded through to `sounddevice.InputStream`, so `set_device` actually selects the input device
- Fixed an event-ordering bug where `state_changed("listening")` was broadcast before `speech_end`, leaving client transcript lines unterminated
- Promoted the STT test client into `src/examples/stt_client.py`: lists/selects an input device interactively before starting transcription, replacing the old producer-only example
- Numerous TUI layout/styling fixes: panel borders and separator junctions, scrollbar suppression on `AutoTextArea`, Commands/stdout panel sizing and padding, stable tool-selection highlighting, `ListView` replacing `DataTable` in the Tools panel

## Infrastructure / Documentation

- Reorganised `named_pipes` into `named_pipes.pipes`, `named_pipes.tools`, and `named_pipes.app` packages; `cpipe` moved into `named_pipes.app.cli`
- `SKILL.md` renamed to `HELP.md` across all tool packages
- Added CC-BY-SA-4.0 copyright headers to all Python files
- Added `moonshine-voice` to the `stt` extras
