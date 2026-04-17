## New features

- **`STTNamedPipe`** — real-time speech-to-text server over a named pipe; captures the default microphone and streams transcribed tokens and VAD lifecycle events (`speech_start`, `speech_end`) to all subscribers
- **Voxtral backend** — Voxtral Mini 4B Realtime (6-bit) vendored under `named_pipes/stt/voxtral/`; switched from Whisper to Voxtral Realtime with progressive token streaming
- **Silero VAD** — replaced RMS silence detection with Silero VAD for more accurate speech onset/end detection
- **STT callbacks** — `on_token`, `on_speech_start`, `on_speech_end` callbacks and a `stop_event` for clean shutdown of the transcription thread
- **`ex_stt_pipe` example** — server and subscriber client demonstrating STT broadcast

## Improvements

- Parallelised STT partial transcriptions via `ThreadPoolExecutor`
- `STT` optional dependency group added to `pyproject.toml`

## Infrastructure

- Switched CI from pip to `uv`; fixed mlx test skipping on Linux, ruff invocation via `uvx`, and vllm resolution in the pytest step

## Documentation

- Rewrote `README.md` following a highlights-first structure; moved detailed architecture, API reference, and design rationale into a new `DOCS.md`
- Added `SKILL.md` files for the chat and TTS servers (loaded from the caller's directory)
