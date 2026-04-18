## New features

- **`STTState` enum** — `STTNamedPipe` now tracks lifecycle state: `loading` (models loading), `listening` (waiting for speech), `transcribing` (speech detected, decoding tokens), `error`
- **`TTSState` enum** — `TTSNamedPipe` now tracks lifecycle state: `loading` (model loading), `idle` (queue empty), `synthesizing` (generating audio for a sentence), `error`
- **`verbose` flag** — `ChatConfig`, `STTConfig`, and `TTSConfig` each gain a `verbose: bool = False` field; when enabled, servers print inference output and progress to stdout

## Improvements

- **Handler refactor** — `ChatNamedPipe` and `ToolNamedPipe` built-in handlers moved from inline closures to named methods (`_handle_chat`, `_handle_chat_blocking`, `_register_builtin_handlers`), making them independently testable
- **`on_ready` callback** — `stream_transcribe` now accepts an optional `on_ready` callback invoked after both the Voxtral ASR model and Silero VAD finish loading, used by `STTNamedPipe` to transition from `loading` to `listening`
- **`state_changed` broadcasts** — all three concrete servers (`chat`, `stt`, `tts`) now broadcast `{"event": "state_changed", "state": "<value>"}` to subscribers on every state transition

## Infrastructure / Documentation

- **Protocol spec** (`named-pipe-tools.md`) — new "Tool State" section documenting the `state_changed` broadcast, base states, and extended states for all three tools
- **Tool READMEs** (`chat`, `stt`, `tts`) — each README now includes a States section describing valid state values and when each occurs
