# STTNamedPipe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a streaming speech-to-text named-pipe tool (`STTNamedPipe` at `/tmp/tool-stt`) that captures mic audio as soon as it is instantiated and broadcasts Voxtral-transcribed tokens and VAD lifecycle events to subscribers.

**Architecture:** Vendor voxmlx's `stream_transcribe` into `named_pipes.stt.voxtral`, add two additive hooks (`on_token`, `stop_event`), and wrap it in an `STTNamedPipe` subclass of `ToolNamedPipe` that runs `stream_transcribe` on a background thread and broadcasts each token / VAD event as a JSON message.

**Tech Stack:** Python 3.11+, `sounddevice`, `torch` (Silero VAD via `torch.hub`), `mlx` + vendored MLX code from voxmlx, existing `named_pipes` library (`ToolNamedPipe`, `broadcast_message`).

**Spec:** `docs/superpowers/specs/2026-04-16-stt-named-pipe-design.md`

**Notes on testing in this plan:**

- The audio pipeline (mic → VAD → MLX decode) is excluded from automated tests per the spec — it requires hardware (microphone) and a 4 GB model download.
- Unit tests in this plan focus on (a) successful imports after vendoring, (b) presence of the new `on_token` / `stop_event` parameters in `stream_transcribe`, and (c) `STTNamedPipe`'s broadcast handlers producing the correct JSON payloads.
- Success criteria 2 and 3 from the spec require manual validation with a real microphone. The final task provides an explicit manual verification script.

---

## Task 1: Vendor voxmlx into `named_pipes.stt.voxtral`

**Files:**
- Create: `src/named_pipes/stt/__init__.py`
- Create: `src/named_pipes/stt/voxtral/__init__.py` (copy of `voxmlx/voxmlx/__init__.py`)
- Create: `src/named_pipes/stt/voxtral/audio.py` (copy)
- Create: `src/named_pipes/stt/voxtral/cache.py` (copy)
- Create: `src/named_pipes/stt/voxtral/convert.py` (copy)
- Create: `src/named_pipes/stt/voxtral/encoder.py` (copy)
- Create: `src/named_pipes/stt/voxtral/generate.py` (copy)
- Create: `src/named_pipes/stt/voxtral/language_model.py` (copy)
- Create: `src/named_pipes/stt/voxtral/model.py` (copy)
- Create: `src/named_pipes/stt/voxtral/stream.py` (copy)
- Create: `src/named_pipes/stt/voxtral/weights.py` (copy)
- Test: `tests/test_stt_voxtral_vendor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stt_voxtral_vendor.py
"""Verifies voxmlx source files are vendored into named_pipes.stt.voxtral and importable."""


def test_voxtral_subpackage_importable():
    # This is the public entry point used by STTNamedPipe.
    from named_pipes.stt.voxtral.stream import stream_transcribe  # noqa: F401


def test_all_voxtral_modules_importable():
    import importlib

    for name in [
        "audio",
        "cache",
        "convert",
        "encoder",
        "generate",
        "language_model",
        "model",
        "stream",
        "weights",
    ]:
        importlib.import_module(f"named_pipes.stt.voxtral.{name}")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stt_voxtral_vendor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'named_pipes.stt'`.

- [ ] **Step 3: Create the `stt/` subpackage and copy voxmlx sources**

Run these commands in order:

```bash
mkdir -p src/named_pipes/stt/voxtral
touch src/named_pipes/stt/__init__.py
cp /Users/stefanwebb/Code/Python/voxmlx/voxmlx/__init__.py         src/named_pipes/stt/voxtral/__init__.py
cp /Users/stefanwebb/Code/Python/voxmlx/voxmlx/audio.py            src/named_pipes/stt/voxtral/audio.py
cp /Users/stefanwebb/Code/Python/voxmlx/voxmlx/cache.py            src/named_pipes/stt/voxtral/cache.py
cp /Users/stefanwebb/Code/Python/voxmlx/voxmlx/convert.py          src/named_pipes/stt/voxtral/convert.py
cp /Users/stefanwebb/Code/Python/voxmlx/voxmlx/encoder.py          src/named_pipes/stt/voxtral/encoder.py
cp /Users/stefanwebb/Code/Python/voxmlx/voxmlx/generate.py         src/named_pipes/stt/voxtral/generate.py
cp /Users/stefanwebb/Code/Python/voxmlx/voxmlx/language_model.py   src/named_pipes/stt/voxtral/language_model.py
cp /Users/stefanwebb/Code/Python/voxmlx/voxmlx/model.py            src/named_pipes/stt/voxtral/model.py
cp /Users/stefanwebb/Code/Python/voxmlx/voxmlx/stream.py           src/named_pipes/stt/voxtral/stream.py
cp /Users/stefanwebb/Code/Python/voxmlx/voxmlx/weights.py          src/named_pipes/stt/voxtral/weights.py
```

Leave `src/named_pipes/stt/__init__.py` empty for now — the `STTNamedPipe` re-export is added in Task 4.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_stt_voxtral_vendor.py -v`
Expected: both tests PASS. If an import fails inside one of the voxtral files, it means that file transitively imports `voxmlx` somewhere — search the copied files for `import voxmlx` / `from voxmlx` and fix any stragglers by replacing with relative imports (there should be none based on the source, but check).

- [ ] **Step 5: Commit**

```bash
git add src/named_pipes/stt tests/test_stt_voxtral_vendor.py
git commit -m "Vendor voxmlx into named_pipes.stt.voxtral"
```

---

## Task 2: Add `on_token` callback to `stream_transcribe`

**Files:**
- Modify: `src/named_pipes/stt/voxtral/stream.py`
- Test: `tests/test_stt_voxtral_stream_api.py`

**Context:** In the vendored `stream.py`, per-token emission happens at two sites inside `stream_transcribe`:
1. `decode_steps` — after `text = sp.decode(...)`, a `print(text, end="", flush=True)`.
2. `flush_and_reset` — after the final `decode_steps` call, a tail `print(text, end="", flush=True)`.

We add a new `on_token: Callable[[str], None] | None = None` keyword argument. When non-`None`, both sites call `on_token(text)` instead of `print(text, end="", flush=True)`. When `None`, the current `print` behavior is preserved (so the CLI `main()` in `__init__.py` / `stream.py` still works unchanged).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stt_voxtral_stream_api.py
"""Verifies the additive parameters on stream_transcribe."""

import inspect

from named_pipes.stt.voxtral.stream import stream_transcribe


def test_stream_transcribe_has_on_token_kwarg():
    sig = inspect.signature(stream_transcribe)
    assert "on_token" in sig.parameters
    assert sig.parameters["on_token"].default is None


def test_stream_transcribe_source_routes_tokens_through_on_token():
    """Both token-emission sites call on_token when it is provided."""
    src = inspect.getsource(stream_transcribe)
    # Regardless of formatting, both branches should exist.
    assert "on_token(text)" in src
    # The print-fallback must still exist for CLI use.
    assert 'print(text, end=""' in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stt_voxtral_stream_api.py::test_stream_transcribe_has_on_token_kwarg -v`
Expected: FAIL (the parameter does not exist yet).

- [ ] **Step 3: Add the `on_token` parameter and route both emission sites through it**

Edit `src/named_pipes/stt/voxtral/stream.py`. Make three changes:

**Change 3a** — add the import at the top of the file if not already present:

```python
from typing import Callable, Optional
```

**Change 3b** — add `on_token` to the signature of `stream_transcribe`. Find:

```python
def stream_transcribe(
    model_path: str = "mlx-community/Voxtral-Mini-4B-Realtime-6bit",
    temperature: float = 0.0,
    vad_onset: int = 2,
    vad_offset: int = 32,
    notify_on_eos: bool = False,
    on_speaking_started=lambda: print("\non_speaking_started", flush=True),
    on_speaking_finished=lambda: print("on_speaking_finished", flush=True),
):
```

Change it to:

```python
def stream_transcribe(
    model_path: str = "mlx-community/Voxtral-Mini-4B-Realtime-6bit",
    temperature: float = 0.0,
    vad_onset: int = 2,
    vad_offset: int = 32,
    notify_on_eos: bool = False,
    on_speaking_started=lambda: print("\non_speaking_started", flush=True),
    on_speaking_finished=lambda: print("on_speaking_finished", flush=True),
    on_token: Optional[Callable[[str], None]] = None,
):
```

**Change 3c** — replace the two `print(text, end="", flush=True)` emission sites. Find (inside `decode_steps`):

```python
            text = sp.decode(
                [token_id], special_token_policy=SpecialTokenPolicy.IGNORE
            )
            print(text, end="", flush=True)
```

Replace with:

```python
            text = sp.decode(
                [token_id], special_token_policy=SpecialTokenPolicy.IGNORE
            )
            if on_token is not None:
                on_token(text)
            else:
                print(text, end="", flush=True)
```

Find (inside `flush_and_reset`, after the final `decode_steps` block):

```python
            if y is not None:
                token_id = y.item()
                if token_id != eos_token_id:
                    text = sp.decode(
                        [token_id], special_token_policy=SpecialTokenPolicy.IGNORE
                    )
                    print(text, end="", flush=True)
            print(flush=True)
```

Replace with:

```python
            if y is not None:
                token_id = y.item()
                if token_id != eos_token_id:
                    text = sp.decode(
                        [token_id], special_token_policy=SpecialTokenPolicy.IGNORE
                    )
                    if on_token is not None:
                        on_token(text)
                    else:
                        print(text, end="", flush=True)
            if on_token is None:
                print(flush=True)
```

The trailing `print(flush=True)` (which writes a newline after each utterance) is CLI-only — it is skipped when `on_token` is in use so that subscribers do not receive a spurious newline token.

Also find the earlier `print(flush=True)` inside `decode_steps` that handles the EOS path:

```python
            if token_id == eos_token_id:
                print(flush=True)
                cache = None
                y = None
                return i, True
```

Replace with:

```python
            if token_id == eos_token_id:
                if on_token is None:
                    print(flush=True)
                cache = None
                y = None
                return i, True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_stt_voxtral_stream_api.py -v`
Expected: both existing tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/named_pipes/stt/voxtral/stream.py tests/test_stt_voxtral_stream_api.py
git commit -m "Add on_token callback to stream_transcribe"
```

---

## Task 3: Add `stop_event` to `stream_transcribe`

**Files:**
- Modify: `src/named_pipes/stt/voxtral/stream.py`
- Modify: `tests/test_stt_voxtral_stream_api.py` (add a new test case)

- [ ] **Step 1: Add the failing test**

Append this test to `tests/test_stt_voxtral_stream_api.py`:

```python
def test_stream_transcribe_has_stop_event_kwarg():
    sig = inspect.signature(stream_transcribe)
    assert "stop_event" in sig.parameters
    assert sig.parameters["stop_event"].default is None


def test_stream_transcribe_source_checks_stop_event():
    src = inspect.getsource(stream_transcribe)
    # The main loop must break when stop_event is set.
    assert "stop_event" in src
    assert "is_set()" in src
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_stt_voxtral_stream_api.py -v`
Expected: the two new tests FAIL; prior tests still PASS.

- [ ] **Step 3: Add `stop_event` parameter and loop check**

Edit `src/named_pipes/stt/voxtral/stream.py`.

**Change 3a** — add `threading` import at the top if not already present:

```python
import threading
```

(Note: `threading` is already imported in the file — confirm during editing; if present, skip this sub-step.)

**Change 3b** — extend the signature:

```python
def stream_transcribe(
    model_path: str = "mlx-community/Voxtral-Mini-4B-Realtime-6bit",
    temperature: float = 0.0,
    vad_onset: int = 2,
    vad_offset: int = 32,
    notify_on_eos: bool = False,
    on_speaking_started=lambda: print("\non_speaking_started", flush=True),
    on_speaking_finished=lambda: print("on_speaking_finished", flush=True),
    on_token: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
):
```

**Change 3c** — add the check at the top of the main loop. Find:

```python
    try:
        start_time = time.monotonic()
        warned_no_audio = False
        while True:
            # --- Drain mic ---
```

Replace with:

```python
    try:
        start_time = time.monotonic()
        warned_no_audio = False
        while True:
            if stop_event is not None and stop_event.is_set():
                break

            # --- Drain mic ---
```

**Change 3d** — ensure the `finally` block runs on clean stop too. The existing `finally` already handles `stream.stop()`, `stream.close()`, final audio flush. No change needed; the `break` lets control fall through to `finally` naturally.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_stt_voxtral_stream_api.py -v`
Expected: all four tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/named_pipes/stt/voxtral/stream.py tests/test_stt_voxtral_stream_api.py
git commit -m "Add stop_event to stream_transcribe for clean shutdown"
```

---

## Task 4: Implement `STTNamedPipe`

**Files:**
- Create: `src/named_pipes/stt/named_pipe.py`
- Modify: `src/named_pipes/stt/__init__.py` (re-export)
- Test: `tests/test_stt_named_pipe.py`

**Context:** `STTNamedPipe` subclasses `ToolNamedPipe`. On construction it starts a daemon thread that runs the vendored `stream_transcribe`, passing in the three callbacks (`on_token`, `on_speaking_started`, `on_speaking_finished`) and a `threading.Event` for shutdown. Each callback broadcasts a JSON message to all subscribers. Broadcasts are serialized by a lock so tokens don't interleave on the wire.

Look at `src/named_pipes/tts_named_pipe.py` for the pattern to mirror (constructor kwargs, worker thread, `_close` override, `self.handler(...)` registration — though here there are no custom commands to register).

**Note on the test strategy:** to avoid starting the real Voxtral model in unit tests, the test monkey-patches `named_pipes.stt.named_pipe.stream_transcribe` with a stub that waits on the stop event. The test then invokes the broadcast callbacks directly (which is how the real `stream_transcribe` would call them) and asserts that the JSON messages reach a local subscriber.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stt_named_pipe.py
"""Unit tests for STTNamedPipe.

stream_transcribe is stubbed so tests do not require a mic or model. We verify
that the three broadcast callbacks produce the correct JSON messages and that
_close() cleanly stops the worker thread.
"""

import json
import threading
import time

import pytest

import named_pipes.stt.named_pipe as stt_mod
from named_pipes.stt import STTNamedPipe
from named_pipes.text_named_pipe import Role, TextNamedPipe


class _StubStreamTranscribe:
    """Stand-in for voxtral.stream.stream_transcribe.

    Captures the callbacks passed by STTNamedPipe and blocks until
    stop_event is set. Tests invoke the captured callbacks directly.
    """

    def __init__(self):
        self.on_token = None
        self.on_start = None
        self.on_end = None
        self.stop_event = None
        self.entered = threading.Event()

    def __call__(self, **kwargs):
        self.on_token = kwargs["on_token"]
        self.on_start = kwargs["on_speaking_started"]
        self.on_end = kwargs["on_speaking_finished"]
        self.stop_event = kwargs["stop_event"]
        self.entered.set()
        # Block until _close() sets stop_event.
        self.stop_event.wait()


@pytest.fixture
def stub(monkeypatch):
    stub = _StubStreamTranscribe()
    monkeypatch.setattr(stt_mod, "stream_transcribe", stub)
    return stub


def _collect_messages(pid: int, path: str, count: int, timeout: float = 2.0) -> list[dict]:
    """Subscribe a client-side reader and collect `count` JSON messages."""
    client = TextNamedPipe(path, Role.CLIENT)
    # Subscribe (use raw send_message — we do not need ToolNamedPipe client APIs here).
    client.send_message(json.dumps({"pid": client._pid, "cmd": "subscribe"}))

    collected: list[dict] = []
    deadline = time.monotonic() + timeout

    def reader():
        while len(collected) < count and time.monotonic() < deadline:
            try:
                msg = client.recv_message()
            except Exception:
                return
            # Ignore the subscribe ack ({"result": "subscribed"}).
            if msg.get("result") == "subscribed":
                continue
            collected.append(msg)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t.join(timeout=timeout + 0.5)
    client._close()
    return collected


def test_construct_starts_worker_with_callbacks(stub):
    pipe = STTNamedPipe("stt-test")
    try:
        assert stub.entered.wait(timeout=2.0), "worker thread never started"
        assert callable(stub.on_token)
        assert callable(stub.on_start)
        assert callable(stub.on_end)
        assert isinstance(stub.stop_event, threading.Event)
    finally:
        pipe._close()


def test_on_token_broadcasts_result_json(stub):
    with STTNamedPipe("stt-test") as pipe:
        pipe.listen()
        assert stub.entered.wait(timeout=2.0)
        # Connect a subscriber, invoke the callback, collect the broadcast.
        # Start the subscriber collection on a thread, then fire the callback.
        collected: list[dict] = []
        done = threading.Event()

        def run():
            collected.extend(_collect_messages(0, "/tmp/tool-stt-test", count=1))
            done.set()

        reader = threading.Thread(target=run, daemon=True)
        reader.start()
        time.sleep(0.2)  # let subscribe reach the server
        stub.on_token("hello")
        done.wait(timeout=2.0)

        assert collected == [{"result": "hello"}]


def test_on_speaking_events_broadcast_speech_start_end(stub):
    with STTNamedPipe("stt-test") as pipe:
        pipe.listen()
        assert stub.entered.wait(timeout=2.0)
        collected: list[dict] = []
        done = threading.Event()

        def run():
            collected.extend(_collect_messages(0, "/tmp/tool-stt-test", count=2))
            done.set()

        reader = threading.Thread(target=run, daemon=True)
        reader.start()
        time.sleep(0.2)
        stub.on_start()
        stub.on_end()
        done.wait(timeout=2.0)

        assert collected == [
            {"event": "speech_start"},
            {"event": "speech_end"},
        ]


def test_close_sets_stop_event_and_joins_worker(stub):
    pipe = STTNamedPipe("stt-test")
    assert stub.entered.wait(timeout=2.0)
    pipe._close()
    # After _close(), the worker should have exited (stop_event was set).
    assert stub.stop_event.is_set()
    assert not pipe._worker.is_alive()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stt_named_pipe.py -v`
Expected: FAIL with `ImportError: cannot import name 'STTNamedPipe' from 'named_pipes.stt'`.

- [ ] **Step 3: Implement `STTNamedPipe`**

Create `src/named_pipes/stt/named_pipe.py`:

```python
"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

STTNamedPipe — a named-pipe tool that streams speech-to-text transcription
from the default microphone to all subscribers.

On construction the class starts a background thread running the vendored
voxtral stream_transcribe loop. Per-token output is broadcast as
{"result": "<token>"}; VAD speech-start / speech-end events are broadcast as
{"event": "speech_start"} / {"event": "speech_end"}. The tool has no custom
commands — it is producer-only.
"""

import json
import threading

from named_pipes.stt.voxtral.stream import stream_transcribe
from named_pipes.text_named_pipe import Role
from named_pipes.tool_named_pipe import ToolNamedPipe


class STTNamedPipe(ToolNamedPipe):
    """Named-pipe STT server.

    Starts the microphone and the Voxtral streaming decode loop in a daemon
    thread immediately on construction. Tokens and VAD lifecycle events are
    broadcast to every subscriber as JSON messages.
    """

    def __init__(
        self,
        name: str = "stt",
        *,
        model_path: str = "mlx-community/Voxtral-Mini-4B-Realtime-6bit",
        temperature: float = 0.0,
        vad_onset: int = 2,
        vad_offset: int = 32,
    ):
        super().__init__(
            name,
            Role.SERVER,
            description="Real-time speech-to-text server over a named pipe.",
        )
        self._stop_event = threading.Event()
        self._broadcast_lock = threading.Lock()

        self._worker = threading.Thread(
            target=stream_transcribe,
            kwargs={
                "model_path": model_path,
                "temperature": temperature,
                "vad_onset": vad_onset,
                "vad_offset": vad_offset,
                "on_token": self._on_token,
                "on_speaking_started": self._on_start,
                "on_speaking_finished": self._on_end,
                "stop_event": self._stop_event,
            },
            daemon=True,
            name="stt-worker",
        )
        self._worker.start()

    # -----------------------------------------------------------------------
    # Broadcast callbacks (called from the worker thread)
    # -----------------------------------------------------------------------

    def _on_token(self, text: str) -> None:
        with self._broadcast_lock:
            self.broadcast_message(json.dumps({"result": text}))

    def _on_start(self) -> None:
        with self._broadcast_lock:
            self.broadcast_message(json.dumps({"event": "speech_start"}))

    def _on_end(self) -> None:
        with self._broadcast_lock:
            self.broadcast_message(json.dumps({"event": "speech_end"}))

    # -----------------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------------

    def _close(self):
        self._stop_event.set()
        self._worker.join(timeout=5)
        super()._close()
```

Replace the contents of `src/named_pipes/stt/__init__.py` with:

```python
"""Streaming speech-to-text over a named pipe."""

from named_pipes.stt.named_pipe import STTNamedPipe

__all__ = ["STTNamedPipe"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_stt_named_pipe.py -v`
Expected: all four tests PASS.

If `test_on_token_broadcasts_result_json` or `test_on_speaking_events_broadcast_speech_start_end` are flaky due to the fixed `time.sleep(0.2)`, bump the sleep to 0.5 s rather than adding retries — the flakiness is just subscribe-ack ordering.

- [ ] **Step 5: Commit**

```bash
git add src/named_pipes/stt/__init__.py src/named_pipes/stt/named_pipe.py tests/test_stt_named_pipe.py
git commit -m "Add STTNamedPipe broadcasting tokens and VAD events"
```

---

## Task 5: Example server and SKILL.md

**Files:**
- Create: `src/ex_stt_pipe/server.py`
- Create: `src/ex_stt_pipe/SKILL.md`

- [ ] **Step 1: Create the server entrypoint**

Create `src/ex_stt_pipe/server.py`:

```python
"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

STT server: loads Voxtral Realtime via vendored voxtral, captures the default
microphone, and broadcasts transcribed tokens plus VAD speech-start /
speech-end events to all subscribers of /tmp/tool-stt.
"""

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

- [ ] **Step 2: Create the SKILL.md protocol doc**

Create `src/ex_stt_pipe/SKILL.md`:

```markdown
# stt — real-time speech-to-text over a named pipe

Captures audio from the default microphone and broadcasts transcribed tokens in real time, using **Voxtral Mini 4B Realtime** (vendored MLX implementation). Speech onset and end are detected with Silero VAD; subscribers see an utterance-bracketed stream of token messages.

Pipe: `/tmp/tool-stt`

## Built-in commands

| Command | Request | Response |
|---|---|---|
| `subscribe` | `{"pid": <int>, "cmd": "subscribe"}` | `{"result": "subscribed"}` |
| `unsubscribe` | `{"pid": <int>, "cmd": "unsubscribe"}` | *(none)* |
| `description` | `{"pid": <int>, "cmd": "description"}` | `{"result": "<one-line description>"}` |
| `help` | `{"pid": <int>, "cmd": "help"}` | `{"result": "<this text>"}` |
| `exit` | `{"pid": <int>, "cmd": "exit"}` | `{"result": "exiting"}` broadcast to all subscribers, then server exits |

## Broadcasts

The tool is producer-only; it has no custom request commands. While subscribed, a client receives the following messages in order for each utterance:

| When | Message |
|---|---|
| VAD detects start of speech | `{"event": "speech_start"}` |
| Per token emitted by the decoder | `{"result": "<token>"}` |
| All tokens for the utterance have been emitted and VAD has detected end of speech | `{"event": "speech_end"}` |

Tokens are sub-word pieces as produced by the Voxtral tokenizer — subscribers that want whole words should concatenate consecutive `result` strings until the next `speech_end`.

## Typical usage pattern

1. Start the server (`python src/ex_stt_pipe/server.py`) — model load takes several seconds.
2. Subscribe.
3. Speak into the system default microphone.
4. Receive a stream of `speech_start` / `result` / `speech_end` messages per utterance.
5. Send `unsubscribe` when done; send `exit` to shut the server down cleanly.

Audio capture uses the system default input device; there is no audio returned over the pipe, only text.
```

- [ ] **Step 3: Manual verification of success criteria**

Success criteria 1–4 from the spec require manual validation.

Open two terminals, both with the `named-pipes` conda env active (per project CLAUDE.md).

**Terminal A** — run the server:

```bash
python src/ex_stt_pipe/server.py
```

Expected: after several seconds of model-load log output, the line `STT server listening on /tmp/tool-stt ...` appears. **Criterion 1 passed.**

**Terminal B** — connect a subscriber using `cpipe` (see `named-pipe-tools.md`):

```bash
python -m named_pipes.cpipe stt subscribe
```

Leave this command running; speak one utterance (e.g. "hello world, this is a test") into your microphone. Expected: on Terminal B you see, in order, a line containing `{"event": "speech_start"}`, then one or more `{"result": "<token>"}` lines, then `{"event": "speech_end"}`. **Criterion 2 passed.**

Still in Terminal B, with the subscriber running, send `exit` in a third terminal:

```bash
python -m named_pipes.cpipe stt exit
```

Expected: Terminal A prints "exiting" and the server process exits cleanly (no Python traceback, no need to send Ctrl+C). **Criterion 3 passed.**

For criterion 4, temporarily uninstall the voxmlx editable install and re-run the test suite:

```bash
pip uninstall -y voxmlx
pytest tests/test_stt_named_pipe.py tests/test_stt_voxtral_vendor.py tests/test_stt_voxtral_stream_api.py -v
```

Expected: all tests pass. Restore the install if you need it for other work:

```bash
pip install -e /Users/stefanwebb/Code/Python/voxmlx
```

**Criterion 4 passed.**

- [ ] **Step 4: Commit**

```bash
git add src/ex_stt_pipe/server.py src/ex_stt_pipe/SKILL.md
git commit -m "Add ex_stt_pipe example server and SKILL doc"
```

---

## Final self-check

After Task 5 is committed, verify the whole feature end-to-end:

```bash
pytest tests/test_stt_named_pipe.py tests/test_stt_voxtral_vendor.py tests/test_stt_voxtral_stream_api.py -v
```

All nine tests should pass. Manual verification of success criteria 1–3 was performed in Task 5 Step 3; criterion 4 was verified by uninstalling the editable voxmlx and re-running the suite.
