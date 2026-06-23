## New features

- **Per-word forced-alignment timestamps for STT** — set `align=True` (`STTConfig.align`) to attach absolute-epoch word timestamps to `speech` events; backed by a new `ForcedAligner` wrapper around `mlx-audio`'s `Qwen3-ForcedAligner-0.6B-4bit` and a `CoalescingAligner` background worker that re-aligns on word boundaries plus once at `speech_end`
- **Out-of-process aligner** — `SubprocessAligner` runs the forced aligner in a spawned child process, since concurrent Metal use by the decoder and aligner in one process hangs the server
- **`--align` flag for `cpipe --serve stt`**, and an align toggle in the TUI's STT launcher (now defaulting to on)
- **STT model caching across pause/resume** — Voxtral and Silero VAD are now cached on the server and reused across `pause`/`start` instead of reloading from disk; both load eagerly in a background thread at construction (state `loading` until ready), with the forced aligner warmed concurrently
- **STT console clients rewritten** — `Program.cs` (the C# `ToolClient` demo) and `src/examples/stt_client.py` now list/select an input device, stream live transcription with word timings in place, and detect an already-running session (via `get_state`) to attach to it instead of restarting it; Ctrl+C only sends `pause` if the client itself started the session

## Improvements

- Clients only print word-level timestamps once `speech_end` has fired, instead of re-printing the live partial transcript a second time when the (asynchronous, out-of-process) alignment result arrives late
- Added a wall-clock anchor, `abs_start`, and an `on_audio` callback to `stream_transcribe`, needed to compute absolute word timestamps
- Fixed `pre_roll_starts` falling out of lockstep with `pre_roll` in `flush_and_reset`

## Infrastructure / Documentation

- Added design spec and implementation plan docs for STT per-word forced-alignment timestamps
- Made `named_pipes.stt`'s package `__init__` lazy; repaired a stale `STTServer` test for the lazy-start architecture
