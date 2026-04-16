# STTNamedPipe — streaming speech-to-text over a named pipe

**Date:** 2026-04-16
**Status:** Approved (pending implementation plan)

## Goal

Add a new named-pipe tool that captures audio from the default system microphone as soon as it is instantiated, transcribes it in real time using the Voxtral Realtime model, and broadcasts the resulting text tokens to all subscribed processes.

This is the first iteration — the aim is the smallest coherent implementation, with further features (pause/resume, configurable device, token finality flags, etc.) deferred to later prompts.

## Motivation

The repo already provides a real-time TTS tool (`TTSNamedPipe`, at `/tmp/tool-tts`) that consumes streamed text tokens and emits audio. An STT counterpart closes the loop: subscribers can listen for speech and feed it into an LLM or any other consumer over the same named-pipe protocol.

## Dependency posture

Currently the sibling project `/Users/stefanwebb/Code/Python/voxmlx` is editable-installed as a library. For this change, voxmlx ceases to be a dependency of `named-pipes`: the files required to run `voxmlx.stream.stream_transcribe` are copied ("vendored") into the `named_pipes` package under a new `named_pipes.stt.voxtral` subpackage, which becomes the single source of truth for the Voxtral streaming implementation used here.

## File layout

```
src/named_pipes/stt/
    __init__.py              # re-exports STTNamedPipe
    named_pipe.py            # STTNamedPipe class
    voxtral/
        __init__.py          # copied from voxmlx/__init__.py
        audio.py             # copied from voxmlx
        cache.py             # copied from voxmlx
        convert.py           # copied from voxmlx
        encoder.py           # copied from voxmlx
        generate.py          # copied from voxmlx
        language_model.py    # copied from voxmlx
        model.py             # copied from voxmlx
        stream.py            # copied + modified (see "Modifications" below)
        weights.py           # copied from voxmlx
```

All `.py` files under `voxmlx/voxmlx/` are copied wholesale to start; pruning unused files is deferred (see "Out of scope"). This avoids import-time breakage — e.g. `voxmlx/__init__.py` imports from `generate`, so `generate.py` must be present for `from named_pipes.stt.voxtral import stream_transcribe` to succeed.

Example server and protocol doc:

```
src/ex_stt_pipe/
    server.py                # thin entrypoint that instantiates STTNamedPipe
    SKILL.md                 # protocol documentation
```

Public import path: `from named_pipes.stt import STTNamedPipe`.

## Modifications to vendored `voxtral/stream.py`

Two additive parameters on `stream_transcribe`; both default to preserving the current CLI behavior.

1. `on_token: Callable[[str], None] | None = None`
   When provided, called with each decoded token string in place of the existing `print(text, end="", flush=True)` at its two emission sites:
   - inside `decode_steps`, the per-token emission
   - inside `flush_and_reset`, the tail token emitted after the final `decode_steps` call
   When `None`, the current `print` behavior is retained.

2. `stop_event: threading.Event | None = None`
   When provided, the main `while True:` loop checks `if stop_event is not None and stop_event.is_set(): break` once per iteration (after the `time.sleep(0.02)` points). This gives `STTNamedPipe._close` a clean way to end the background thread without relying on `KeyboardInterrupt`. Unrelated startup `print`s (`"Loading VAD..."`, `"Listening..."`) are untouched — they run once at startup and do not carry per-token data.

No other changes to the copied voxtral files are planned. Everything downstream of `stream.py` is used verbatim.

## `STTNamedPipe`

Location: `src/named_pipes/stt/named_pipe.py`, re-exported from `src/named_pipes/stt/__init__.py`.

Subclasses `ToolNamedPipe`. Pipe path: `/tmp/tool-stt`.

### Constructor

```python
STTNamedPipe(
    name: str = "stt",
    *,
    model_path: str = "mlx-community/Voxtral-Mini-4B-Realtime-6bit",
    temperature: float = 0.0,
    vad_onset: int = 2,
    vad_offset: int = 32,
)
```

Defaults mirror `stream_transcribe`. `__init__` must, in order:

1. Call `super().__init__(name, Role.SERVER, description="Real-time speech-to-text server over a named pipe.")`.
2. Initialise `self._stop_event = threading.Event()` and `self._broadcast_lock = threading.Lock()`.
3. Start a daemon thread (`name="stt-worker"`) that calls:
   ```python
   stream_transcribe(
       model_path=model_path,
       temperature=temperature,
       vad_onset=vad_onset,
       vad_offset=vad_offset,
       on_token=self._on_token,
       on_speaking_started=self._on_start,
       on_speaking_finished=self._on_end,
       stop_event=self._stop_event,
   )
   ```

The worker thread starts before `listen()` is ever called; the microphone begins capturing as soon as the class is instantiated (matching the user's "simplest possible" requirement).

### Broadcast handlers

All three take the broadcast lock to serialize messages on the pipe:

- `_on_token(text: str)` → `broadcast_message(json.dumps({"result": text}))`
- `_on_start()` → `broadcast_message(json.dumps({"event": "speech_start"}))`
- `_on_end()` → `broadcast_message(json.dumps({"event": "speech_end"}))`

Broadcasts go to every subscriber; the pipe has no per-subscriber filtering.

### Protocol

Inherits the `ToolNamedPipe` built-ins (`subscribe`, `unsubscribe`, `description`, `help`, `exit`). No custom commands — the tool is producer-only.

Broadcasts (to every subscriber):

| When | Message |
|---|---|
| VAD crosses onset threshold | `{"event": "speech_start"}` |
| Each token emitted by `stream_transcribe` | `{"result": "<token>"}` |
| VAD crosses offset threshold, after tail tokens have been broadcast | `{"event": "speech_end"}` |

### Ordering guarantee: `speech_end` after final tokens

`stream_transcribe` calls `flush_and_reset()` *before* `on_speaking_finished()`, and the decode loop is single-threaded. Consequently, every token of an utterance is emitted via `on_token` before `on_speaking_finished` fires. Subscribers therefore see a deterministic sequence:

```
{"event": "speech_start"}
{"result": "<token_1>"}
... (zero or more tokens) ...
{"result": "<token_n>"}
{"event": "speech_end"}
```

### Cleanup

`_close` (override):

1. `self._stop_event.set()`
2. `self._worker.join(timeout=...)` (conservative timeout, e.g. 5 s)
3. `super()._close()`

The `sounddevice.InputStream` is owned by `stream_transcribe`, which stops and closes it in its own `finally` block on loop exit.

## Example server

`src/ex_stt_pipe/server.py`:

```python
from named_pipes.stt import STTNamedPipe

def main():
    with STTNamedPipe("stt") as ch:
        done = ch.listen()
        print("STT server listening on /tmp/tool-stt ...")
        done.wait()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down.")
```

`src/ex_stt_pipe/SKILL.md` — mirrors `src/ex_tts_pipe/SKILL.md` in structure, documenting the protocol surface above. No custom commands table (there are no custom commands); instead, a "Broadcasts" table covering `speech_start`, per-token `result`, and `speech_end`.

## Error handling

None beyond what `stream_transcribe` already does. Import failures for `sounddevice`, `torch`, or the vendored voxtral modules surface at `STTNamedPipe` construction, by design. Runtime audio errors from `sounddevice` are currently handled inside `stream_transcribe` (or propagate out of the worker thread and end it) — this matches the current voxmlx behavior and is out of scope to harden in this iteration.

## Out of scope (deferred to later iterations)

- Pruning the vendored voxtral package down to the minimum set of files actually required by `stream_transcribe` at import time. Initial vendor copies all `.py` files from `voxmlx/voxmlx/` so nothing breaks at import.
- `pause` / `resume` commands on the pipe.
- A `"final": bool` field on token broadcasts distinguishing intra-utterance partials from the final tail. The protocol is designed so this can be added without breaking existing subscribers.
- Configurable microphone device (currently uses the system default via `sounddevice`).
- Automated tests of the audio pipeline itself (hard to test without a mock mic; the tool will be validated manually for this iteration).
- Support for multiple concurrent `STTNamedPipe` instances on the same machine.

## Success criteria

1. Running `python src/ex_stt_pipe/server.py` loads the model, loads VAD, and prints "STT server listening on /tmp/tool-stt ...".
2. A subscriber connected via the Named Pipe Tools protocol receives, in order, `speech_start`, one or more `result` messages containing non-empty token text, and `speech_end`, for each utterance spoken into the microphone.
3. Sending `exit` to the pipe shuts down the server cleanly without relying on `KeyboardInterrupt`.
4. The `voxmlx` editable install can be uninstalled from the development environment without breaking the `named_pipes` package.
