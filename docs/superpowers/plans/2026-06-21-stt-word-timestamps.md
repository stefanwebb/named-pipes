# STT Per-Word Timestamps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit per-word absolute (Unix-epoch) timestamps in the Voxtral STT server's `speech` messages by running the Qwen3 forced aligner (via `mlx-audio`) over each utterance as it is transcribed.

**Architecture:** Voxtral's `stream.py` gains a sample-accurate wall-clock anchor and two new callbacks (`on_speaking_started(abs_start)`, `on_audio(chunk)`). The server accumulates per-utterance audio, detects word boundaries from token text, and drives a coalesced background aligner thread that re-aligns the utterance-so-far and emits `speech` events carrying absolute word timings. Pure logic (boundary detection, relative→absolute conversion, coalescing) lives in a dependency-free `alignment.py` so it is unit-testable in CI; the MLX model lives behind a Mac-only `aligner.py`.

**Tech Stack:** Python 3.12, `mlx-audio` (MLX, Apple-Silicon), `numpy`, `sounddevice`, `pytest`. Aligner model: `mlx-community/Qwen3-ForcedAligner-0.6B-4bit`.

---

## Background the engineer needs

- **Run tests:** `conda run -n named-pipes python -m pytest <path> -v` (the project uses the `named-pipes` conda env for everything).
- **CI runs on Ubuntu**, where `mlx` is not installable. Tests that need the Voxtral stack guard with `pytest.importorskip("mlx")` (or `"mlx_audio"`) and therefore **skip in CI** — they only run locally on Mac. Keep pure-logic tests free of any `mlx` import so they run in CI.
- **Why `alignment.py` must avoid importing the package's heavy modules:** importing any submodule of `named_pipes.stt` first runs `named_pipes/stt/__init__.py`. Today that eagerly imports `server` → `stream` → `mlx`. Task 2 makes `__init__.py` lazy so `import named_pipes.stt.alignment` does **not** pull in `mlx`.
- **The aligner API** (verified in the installed `mlx-audio`):
  ```python
  from mlx_audio.stt.utils import load_model
  model = load_model("mlx-community/Qwen3-ForcedAligner-0.6B-4bit")
  result = model.generate(audio_np_16k_f32, text="hello world", language="English")
  for item in result:               # ForcedAlignResult is iterable
      item.text, item.start_time, item.end_time   # seconds (rounded to ms), RELATIVE to passed audio
  ```
- **Voxtral capture is 16 kHz mono float32**, exactly what the aligner expects.
- **Current `stream_transcribe` callbacks:** `on_token(text)`, `on_speaking_started()` (no args today), `on_speaking_finished()`, `on_ready()`, `stop_event`.
- **Current `STTServer` (`src/named_pipes/stt/server.py`)** starts the Voxtral worker lazily on the `start` command; `_on_token` broadcasts a `token` event then a cumulative `speech` event; `_on_start`/`_on_end` broadcast `speech_start`/`speech_end`.

## File structure

| File | Responsibility | mlx? |
|---|---|---|
| `src/named_pipes/stt/alignment.py` (new) | Pure helpers: `WordTiming`, `detect_word_boundary`, `to_absolute`, `CoalescingAligner` | no |
| `src/named_pipes/stt/aligner.py` (new) | `ForcedAligner` — lazy MLX model wrapper, `align()` → relative `WordTiming` | yes (lazy) |
| `src/named_pipes/stt/__init__.py` (modify) | Make exports lazy via `__getattr__` | no |
| `src/named_pipes/stt/voxtral/stream.py` (modify) | Wall-clock anchor + `on_speaking_started(abs_start)` + `on_audio(chunk)` | yes |
| `src/named_pipes/stt/server.py` (modify) | Config flags, accumulate audio, boundary→job, emit `speech` with `words` | yes |
| `src/named_pipes/interfaces/stt.py` (modify) | Add `words` field to `speech` `EventSpec` | no |
| `src/examples/stt_client.py` (modify) | Print word timings when present | no |
| `src/named_pipes/stt/README.md` (modify) | Document `align` config + model download | n/a |
| `tests/test_stt_named_pipe.py` (rewrite) | Repair to current architecture | yes-gated |
| `tests/test_stt_alignment.py` (new) | CI-runnable pure-logic tests | no |
| `tests/test_stt_forced_aligner.py` (new) | Mac/model-gated aligner smoke test | yes-gated |
| `tests/test_stt_word_timestamps.py` (new) | Server integration w/ fake aligner | yes-gated |
| `tests/test_stt_voxtral_stream_api.py` (modify) | Assert new stream kwargs/anchor | yes-gated |

---

## Task 1: Repair the stale STT server test (green local baseline)

`tests/test_stt_named_pipe.py` currently imports `named_pipes.text_named_pipe` (moved to `named_pipes.pipes.text`) and assumes the old eager-start architecture, so it errors on collection and blocks the whole local suite. Rewrite it to the current lazy-start behavior.

**Files:**
- Rewrite: `tests/test_stt_named_pipe.py`

- [ ] **Step 1: Run the file to confirm the current failure**

Run: `conda run -n named-pipes python -m pytest tests/test_stt_named_pipe.py -q`
Expected: collection ERROR — `ModuleNotFoundError: No module named 'named_pipes.text_named_pipe'`

- [ ] **Step 2: Rewrite the test file to current architecture**

Replace the **entire** contents of `tests/test_stt_named_pipe.py` with:

```python
"""Unit tests for the Voxtral STTServer.

stream_transcribe is stubbed so tests need no mic or model. The worker starts
lazily on the `start` command, so tests call the start handler directly, then
drive the captured callbacks.
"""

import json
import threading
import time

import pytest

pytest.importorskip("mlx")

import named_pipes.stt.server as stt_mod
from named_pipes.stt import STTConfig, STTServer
from named_pipes.pipes.text import Role, TextNamedPipe


class _StubStreamTranscribe:
    """Stand-in for voxtral.stream.stream_transcribe.

    Captures the callbacks STTServer passes and blocks until stop_event is set.
    """

    def __init__(self):
        self.kwargs = None
        self.on_token = None
        self.on_start = None
        self.on_end = None
        self.on_audio = None
        self.stop_event = None
        self.entered = threading.Event()

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        self.on_token = kwargs["on_token"]
        self.on_start = kwargs["on_speaking_started"]
        self.on_end = kwargs["on_speaking_finished"]
        self.on_audio = kwargs.get("on_audio")
        self.stop_event = kwargs["stop_event"]
        self.entered.set()
        self.stop_event.wait()


@pytest.fixture
def stub(monkeypatch):
    stub = _StubStreamTranscribe()
    monkeypatch.setattr(stt_mod, "stream_transcribe", stub)
    return stub


class _TestClient(TextNamedPipe):
    def msg_handler_fn(self, msg: dict, pid: int | None):
        pass


def _collect_messages(path: str, count: int, timeout: float = 2.0) -> list[dict]:
    client = _TestClient(path, Role.CLIENT)
    client.send_message(json.dumps({"pid": client._pid, "cmd": "subscribe"}))

    collected: list[dict] = []
    deadline = time.monotonic() + timeout

    def reader():
        while len(collected) < count and time.monotonic() < deadline:
            try:
                msg = client.recv_message()
            except Exception:
                return
            if msg.get("event") == "subscribed":
                continue
            collected.append(msg)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t.join(timeout=timeout + 0.5)
    client._close()
    return collected


def test_start_command_starts_worker_with_callbacks(stub):
    pipe = STTServer(STTConfig(name="stt-test"))
    try:
        pipe._handle_start({}, None)
        assert stub.entered.wait(timeout=2.0), "worker thread never started"
        assert callable(stub.on_token)
        assert callable(stub.on_start)
        assert callable(stub.on_end)
        assert isinstance(stub.stop_event, threading.Event)
    finally:
        pipe._close()


def test_on_token_broadcasts_token_and_speech(stub):
    with STTServer(STTConfig(name="stt-test")) as pipe:
        pipe.listen()
        pipe._handle_start({}, None)
        assert stub.entered.wait(timeout=2.0)
        # Begin an utterance so _current_text is reset.
        pipe._on_start(1000.0)

        collected: list[dict] = []
        done = threading.Event()

        def run():
            collected.extend(_collect_messages("/tmp/tool-stt-test", count=2))
            done.set()

        reader = threading.Thread(target=run, daemon=True)
        reader.start()
        time.sleep(0.2)
        stub.on_token("hello")
        done.wait(timeout=2.0)

        events = {(m["event"], m.get("text")) for m in collected}
        assert ("token", "hello") in events
        assert ("speech", "hello") in events


def test_on_speaking_events_broadcast_speech_start_end(stub):
    with STTServer(STTConfig(name="stt-test")) as pipe:
        pipe.listen()
        pipe._handle_start({}, None)
        assert stub.entered.wait(timeout=2.0)

        collected: list[dict] = []
        done = threading.Event()

        def run():
            collected.extend(_collect_messages("/tmp/tool-stt-test", count=4))
            done.set()

        reader = threading.Thread(target=run, daemon=True)
        reader.start()
        time.sleep(0.2)
        stub.on_start(1000.0)
        stub.on_end()
        done.wait(timeout=2.0)

        speech_events = [
            m for m in collected if m.get("event") in ("speech_start", "speech_end")
        ]
        assert {"event": "speech_start"} in speech_events
        assert {"event": "speech_end"} in speech_events


def test_close_sets_stop_event_and_joins_worker(stub):
    pipe = STTServer(STTConfig(name="stt-test"))
    pipe._handle_start({}, None)
    assert stub.entered.wait(timeout=2.0)
    pipe._close()
    assert stub.stop_event.is_set()
    assert not pipe._worker.is_alive()
```

> Note: `test_on_speaking_events_*` and `test_on_token_*` call `pipe._on_start(1000.0)` — `_on_start` will take an `abs_start` argument after Task 6. Task 6 adds that parameter; this test is written for the final signature now so it does not need re-editing.

- [ ] **Step 3: Run the repaired test**

Run: `conda run -n named-pipes python -m pytest tests/test_stt_named_pipe.py -q`
Expected: PASS — but `test_on_speaking_events_*` / `test_on_token_*` / `_on_start(1000.0)` will FAIL right now because the current `_on_start` takes no argument. That is expected; they go green in Task 6.

> Acceptance for Task 1: the file **collects without error** and `test_start_command_starts_worker_with_callbacks` + `test_close_sets_stop_event_and_joins_worker` PASS. The two `_on_start(abs_start)` tests are expected-red until Task 6.

- [ ] **Step 4: Confirm the full local suite collects**

Run: `conda run -n named-pipes python -m pytest tests/ -q --co`
Expected: collection succeeds (no ImportError).

- [ ] **Step 5: Commit**

```bash
git add tests/test_stt_named_pipe.py
git commit -m "$(cat <<'EOF'
test: repair stale STTServer test for lazy-start architecture

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Pure alignment helpers + lazy package init

Create `alignment.py` with `WordTiming`, `detect_word_boundary`, and `to_absolute`, and make `stt/__init__.py` lazy so these helpers (and their tests) import without `mlx`.

**Files:**
- Create: `src/named_pipes/stt/alignment.py`
- Modify: `src/named_pipes/stt/__init__.py`
- Test: `tests/test_stt_alignment.py`

- [ ] **Step 1: Make `stt/__init__.py` lazy**

Replace the **entire** contents of `src/named_pipes/stt/__init__.py` with:

```python
"""© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en
"""

"""Streaming speech-to-text over a named pipe.

Exports are lazy so that importing lightweight submodules (e.g. ``alignment``)
does not pull in the Voxtral/MLX stack.
"""

__all__ = ["STTConfig", "STTServer"]


def __getattr__(name):
    if name in ("STTConfig", "STTServer"):
        from named_pipes.stt.server import STTConfig, STTServer

        return {"STTConfig": STTConfig, "STTServer": STTServer}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_stt_alignment.py`:

```python
"""Pure-logic tests for STT forced-alignment helpers (no mlx, runs in CI)."""

from named_pipes.stt.alignment import (
    WordTiming,
    detect_word_boundary,
    to_absolute,
)


def test_first_nonempty_token_is_a_boundary():
    assert detect_word_boundary("", " Testing") is True


def test_first_blank_token_is_not_a_boundary():
    assert detect_word_boundary("", "   ") is False


def test_leading_space_token_is_a_boundary():
    assert detect_word_boundary(" Testing", " one") is True


def test_continuation_token_is_not_a_boundary():
    assert detect_word_boundary(" Test", "ing") is False


def test_to_absolute_adds_anchor_and_rounds_to_ms():
    items = [WordTiming("hi", 0.08, 0.40), WordTiming("there", 0.56, 0.80)]
    out = to_absolute(items, 1000.001)
    assert out == [
        {"word": "hi", "start": 1000.081, "end": 1000.401},
        {"word": "there", "start": 1000.561, "end": 1000.801},
    ]


def test_to_absolute_empty():
    assert to_absolute([], 1000.0) == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `conda run -n named-pipes python -m pytest tests/test_stt_alignment.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'named_pipes.stt.alignment'`

- [ ] **Step 4: Implement the helpers**

Create `src/named_pipes/stt/alignment.py`:

```python
"""© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

Pure helpers for forced-alignment word timestamps. No MLX / heavy imports, so
this module is unit-testable in CI.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class WordTiming:
    """One aligned word with timestamps in seconds (relative to aligned audio)."""

    word: str
    start: float
    end: float


def detect_word_boundary(prev_text: str, token_text: str) -> bool:
    """Return True if ``token_text`` begins a new word.

    Voxtral emits SentencePiece sub-word tokens; a word-initial token decodes
    with a leading space. The first non-blank token of an utterance also starts
    a word.
    """
    if not prev_text:
        return bool(token_text.strip())
    return token_text[:1].isspace()


def to_absolute(items: list[WordTiming], abs_start: float) -> list[dict]:
    """Convert relative ``WordTiming``s to absolute epoch-second dicts (ms precision)."""
    return [
        {
            "word": it.word,
            "start": round(abs_start + it.start, 3),
            "end": round(abs_start + it.end, 3),
        }
        for it in items
    ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `conda run -n named-pipes python -m pytest tests/test_stt_alignment.py -q`
Expected: PASS (6 passed)

- [ ] **Step 6: Verify lazy init keeps the public import working (Mac)**

Run: `conda run -n named-pipes python -c "from named_pipes.stt import STTConfig; print(STTConfig().name)"`
Expected: prints `stt`

- [ ] **Step 7: Commit**

```bash
git add src/named_pipes/stt/alignment.py src/named_pipes/stt/__init__.py tests/test_stt_alignment.py
git commit -m "$(cat <<'EOF'
feat: add pure forced-alignment helpers; make stt package init lazy

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: CoalescingAligner (background thread, one-slot pending)

Add `CoalescingAligner` to `alignment.py`: a worker thread that runs an injected `align_fn` and forwards results to `emit_fn`, keeping at most one alignment in flight and collapsing intermediate submissions to the latest. Pure (no mlx); testable in CI with a fake `align_fn`.

**Files:**
- Modify: `src/named_pipes/stt/alignment.py`
- Test: `tests/test_stt_alignment.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_stt_alignment.py`:

```python
import threading
import time

from named_pipes.stt.alignment import CoalescingAligner


def test_runs_submitted_job_and_emits():
    emits = []
    ca = CoalescingAligner(
        align_fn=lambda audio, text: [WordTiming(text, 0.0, 0.5)],
        emit_fn=lambda items, text, abs_start: emits.append((items[0].word, text, abs_start)),
    )
    ca.submit("audio", "hello", 100.0)
    deadline = time.monotonic() + 2.0
    while not emits and time.monotonic() < deadline:
        time.sleep(0.01)
    ca.stop()
    assert emits == [("hello", "hello", 100.0)]


def test_coalesces_intermediate_submissions():
    started = threading.Event()
    release = threading.Event()
    calls = []
    emits = []

    def align_fn(audio, text):
        calls.append(text)
        if text == "A":
            started.set()
            release.wait(2.0)
        return [WordTiming(text, 0.0, 0.1)]

    ca = CoalescingAligner(
        align_fn=align_fn,
        emit_fn=lambda items, text, abs_start: emits.append(text),
    )
    ca.submit("a", "A", 1.0)
    assert started.wait(2.0)        # "A" is running
    ca.submit("b", "B", 2.0)        # queued
    ca.submit("c", "C", 3.0)        # overwrites "B"
    release.set()
    deadline = time.monotonic() + 2.0
    while len(emits) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    ca.stop()
    assert calls == ["A", "C"]      # "B" coalesced away
    assert emits == ["A", "C"]


def test_align_exception_calls_on_error_and_keeps_running():
    errors = []
    emits = []

    def align_fn(audio, text):
        if text == "bad":
            raise RuntimeError("boom")
        return [WordTiming(text, 0.0, 0.1)]

    ca = CoalescingAligner(
        align_fn=align_fn,
        emit_fn=lambda items, text, abs_start: emits.append(text),
        on_error=lambda exc: errors.append(str(exc)),
    )
    ca.submit("x", "bad", 1.0)
    deadline = time.monotonic() + 2.0
    while not errors and time.monotonic() < deadline:
        time.sleep(0.01)
    ca.submit("y", "good", 2.0)
    deadline = time.monotonic() + 2.0
    while not emits and time.monotonic() < deadline:
        time.sleep(0.01)
    ca.stop()
    assert errors == ["boom"]
    assert emits == ["good"]


def test_stop_drains_final_pending_job():
    emits = []
    ca = CoalescingAligner(
        align_fn=lambda audio, text: [WordTiming(text, 0.0, 0.1)],
        emit_fn=lambda items, text, abs_start: emits.append(text),
    )
    ca.submit("z", "final", 1.0)
    ca.stop()                       # must process the pending job before exiting
    assert emits == ["final"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n named-pipes python -m pytest tests/test_stt_alignment.py -q`
Expected: FAIL — `ImportError: cannot import name 'CoalescingAligner'`

- [ ] **Step 3: Implement CoalescingAligner**

Append to `src/named_pipes/stt/alignment.py`:

```python
import threading
from typing import Callable, Optional


class CoalescingAligner:
    """Runs ``align_fn`` in a background thread, coalescing rapid submissions.

    At most one alignment runs at a time. Submissions that arrive while one is
    running overwrite each other, so only the latest pending job runs next.
    Results are forwarded to ``emit_fn(items, text, abs_start)``. Exceptions in
    ``align_fn`` go to ``on_error`` (if given) and never kill the worker.
    """

    def __init__(
        self,
        align_fn: Callable[[object, str], list],
        emit_fn: Callable[[list, str, float], None],
        on_error: Optional[Callable[[Exception], None]] = None,
    ):
        self._align_fn = align_fn
        self._emit_fn = emit_fn
        self._on_error = on_error
        self._cond = threading.Condition()
        self._pending: Optional[tuple] = None
        self._stop = False
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="stt-aligner"
        )
        self._thread.start()

    def submit(self, audio, text: str, abs_start: float) -> None:
        with self._cond:
            self._pending = (audio, text, abs_start)
            self._cond.notify()

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._pending is None and not self._stop:
                    self._cond.wait()
                if self._pending is None and self._stop:
                    return
                audio, text, abs_start = self._pending
                self._pending = None
            try:
                items = self._align_fn(audio, text)
                self._emit_fn(items, text, abs_start)
            except Exception as exc:  # noqa: BLE001 - degrade gracefully
                if self._on_error is not None:
                    self._on_error(exc)

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify()
        self._thread.join(timeout=5)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n named-pipes python -m pytest tests/test_stt_alignment.py -q`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add src/named_pipes/stt/alignment.py tests/test_stt_alignment.py
git commit -m "$(cat <<'EOF'
feat: add CoalescingAligner background worker for forced alignment

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: ForcedAligner MLX wrapper

Wrap the `mlx-audio` Qwen3 aligner behind a small lazy-loading class returning relative `WordTiming`s.

**Files:**
- Create: `src/named_pipes/stt/aligner.py`
- Test: `tests/test_stt_forced_aligner.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stt_forced_aligner.py`:

```python
"""Tests for the MLX ForcedAligner wrapper (Mac-only; model test is gated)."""

import os

import numpy as np
import pytest

pytest.importorskip("mlx_audio")

from named_pipes.stt.aligner import DEFAULT_ALIGN_MODEL, ForcedAligner
from named_pipes.stt.alignment import WordTiming


def _hf_cache_dir() -> str:
    return (
        os.environ.get("HF_HUB_CACHE")
        or os.environ.get("HUGGINGFACE_HUB_CACHE")
        or os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    )


def _model_cached(model_id: str) -> bool:
    model_dir = model_id.replace("/", "--")
    return os.path.isdir(os.path.join(_hf_cache_dir(), f"models--{model_dir}"))


def test_available_is_false_before_load():
    aligner = ForcedAligner()
    assert aligner.available is False


def test_load_failure_sets_failed(monkeypatch):
    aligner = ForcedAligner(model_id="does-not-exist/nope")

    def boom(*a, **k):
        raise RuntimeError("no such model")

    monkeypatch.setattr("mlx_audio.stt.utils.load_model", boom)
    with pytest.raises(RuntimeError):
        aligner.load()
    assert aligner.available is False


@pytest.mark.skipif(
    not _model_cached(DEFAULT_ALIGN_MODEL),
    reason=f"aligner model {DEFAULT_ALIGN_MODEL} not downloaded (hf download {DEFAULT_ALIGN_MODEL})",
)
def test_align_returns_word_timings():
    aligner = ForcedAligner()
    aligner.load()
    assert aligner.available is True
    # 1.5 s of low-level noise; we assert structure, not transcription accuracy.
    rng = np.random.default_rng(0)
    audio = (rng.standard_normal(int(1.5 * 16000)).astype(np.float32)) * 0.01
    result = aligner.align(audio, "hello world")
    assert isinstance(result, list)
    assert all(isinstance(w, WordTiming) for w in result)
    for w in result:
        assert w.start <= w.end
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n named-pipes python -m pytest tests/test_stt_forced_aligner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'named_pipes.stt.aligner'`

- [ ] **Step 3: Implement the wrapper**

Create `src/named_pipes/stt/aligner.py`:

```python
"""© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

ForcedAligner — lazy wrapper around the mlx-audio Qwen3 forced aligner. Returns
per-word timings in seconds RELATIVE to the audio it is given.
"""

import numpy as np

from named_pipes.stt.alignment import WordTiming

DEFAULT_ALIGN_MODEL = "mlx-community/Qwen3-ForcedAligner-0.6B-4bit"


class ForcedAligner:
    """Lazily loads the MLX aligner and aligns (audio, text) pairs."""

    def __init__(self, model_id: str = DEFAULT_ALIGN_MODEL, language: str = "English"):
        self._model_id = model_id
        self._language = language
        self._model = None
        self._failed = False

    @property
    def available(self) -> bool:
        return self._model is not None and not self._failed

    def load(self) -> None:
        if self._model is not None or self._failed:
            return
        try:
            from mlx_audio.stt.utils import load_model

            self._model = load_model(self._model_id)
        except Exception:
            self._failed = True
            raise

    def align(self, audio_16k_f32: np.ndarray, text: str) -> list[WordTiming]:
        """Align ``text`` to 16 kHz mono float32 ``audio``; relative-second timings."""
        if self._model is None:
            self.load()
        result = self._model.generate(audio_16k_f32, text=text, language=self._language)
        return [
            WordTiming(str(it.text), float(it.start_time), float(it.end_time))
            for it in result
        ]
```

- [ ] **Step 4: Run tests to verify they pass (or skip the model test)**

Run: `conda run -n named-pipes python -m pytest tests/test_stt_forced_aligner.py -q`
Expected: `test_available_is_false_before_load` and `test_load_failure_sets_failed` PASS; `test_align_returns_word_timings` PASSES if the model is cached, else SKIPS.

- [ ] **Step 5: Commit**

```bash
git add src/named_pipes/stt/aligner.py tests/test_stt_forced_aligner.py
git commit -m "$(cat <<'EOF'
feat: add MLX ForcedAligner wrapper (Qwen3-ForcedAligner-0.6B-4bit)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: stream.py — wall-clock anchor + on_speaking_started(abs_start) + on_audio

Add a sample-accurate wall-clock anchor, deliver the utterance's absolute start time through `on_speaking_started`, and stream utterance speech samples through a new `on_audio` callback.

**Files:**
- Modify: `src/named_pipes/stt/voxtral/stream.py`
- Test: `tests/test_stt_voxtral_stream_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_stt_voxtral_stream_api.py`:

```python
def test_stream_transcribe_has_on_audio_kwarg():
    sig = inspect.signature(stream_transcribe)
    assert "on_audio" in sig.parameters
    assert sig.parameters["on_audio"].default is None


def test_stream_transcribe_passes_abs_start_to_on_speaking_started():
    src = inspect.getsource(stream_transcribe)
    assert "on_speaking_started(abs_start)" in src


def test_stream_transcribe_maintains_wall_clock_anchor():
    src = inspect.getsource(stream_transcribe)
    assert "inputBufferAdcTime" in src
    assert "samples_captured" in src


def test_stream_transcribe_routes_audio_through_on_audio():
    src = inspect.getsource(stream_transcribe)
    assert "on_audio(" in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n named-pipes python -m pytest tests/test_stt_voxtral_stream_api.py -q`
Expected: FAIL on the four new tests (`on_audio` kwarg missing, etc.)

- [ ] **Step 3: Add the `on_audio` parameter**

In `src/named_pipes/stt/voxtral/stream.py`, change the signature block (currently lines ~75-80) from:

```python
    on_speaking_started=lambda: print("\non_speaking_started", flush=True),
    on_speaking_finished=lambda: print("on_speaking_finished", flush=True),
    on_token: Optional[Callable[[str], None]] = None,
    on_ready: Optional[Callable[[], None]] = None,
    stop_event: Optional[threading.Event] = None,
    device: Optional[int] = None,
```

to:

```python
    on_speaking_started=lambda abs_start: print("\non_speaking_started", flush=True),
    on_speaking_finished=lambda: print("on_speaking_finished", flush=True),
    on_token: Optional[Callable[[str], None]] = None,
    on_ready: Optional[Callable[[], None]] = None,
    on_audio: Optional[Callable[[object], None]] = None,
    stop_event: Optional[threading.Event] = None,
    device: Optional[int] = None,
```

- [ ] **Step 4: Add the wall-clock anchor + sample counter in the callback**

Replace the audio-buffer/callback block (currently lines ~146-153):

```python
    # Audio buffer and lock
    lock = threading.Lock()
    audio_buf = np.zeros(0, dtype=np.float32)

    def callback(indata, frames, time_info, status):
        nonlocal audio_buf
        with lock:
            audio_buf = np.append(audio_buf, indata[:, 0])
```

with:

```python
    # Audio buffer and lock
    lock = threading.Lock()
    audio_buf = np.zeros(0, dtype=np.float32)

    # Wall-clock anchor: map global sample 0 to a wall-clock time so each
    # captured sample has an absolute timestamp. PortAudio's input latency
    # (currentTime - inputBufferAdcTime) is subtracted so the anchor is the
    # time the first sample was captured at the ADC.
    sr = 16000
    samples_captured = 0
    wall0 = None

    def callback(indata, frames, time_info, status):
        nonlocal audio_buf, samples_captured, wall0
        with lock:
            if wall0 is None:
                try:
                    latency = time_info.currentTime - time_info.inputBufferAdcTime
                except Exception:
                    latency = 0.0
                wall0 = time.time() - latency - samples_captured / sr
            audio_buf = np.append(audio_buf, indata[:, 0])
            samples_captured += frames
```

- [ ] **Step 5: Track drained-sample positions and a pre-roll start index**

Find the pre-roll declaration (search for `pre_roll: collections.deque`) and add a parallel deque + a drain counter immediately after it:

```python
    pre_roll: collections.deque = collections.deque(maxlen=PRE_ROLL_BLOCKS)
    pre_roll_starts: collections.deque = collections.deque(maxlen=PRE_ROLL_BLOCKS)
    global_pos = 0  # number of samples drained from audio_buf so far
```

- [ ] **Step 6: Compute each drained chunk's global start index**

Replace the drain block (currently lines ~260-263):

```python
            # --- Drain mic ---
            with lock:
                new_audio = audio_buf
                audio_buf = np.zeros(0, dtype=np.float32)
```

with:

```python
            # --- Drain mic ---
            with lock:
                new_audio = audio_buf
                audio_buf = np.zeros(0, dtype=np.float32)
            chunk_start = global_pos
            global_pos += len(new_audio)
```

- [ ] **Step 7: Remove the in-VAD-loop `on_speaking_started()` call**

In the VAD prob loop (currently line ~279) delete the bare call so the callback fires once, with `abs_start`, in the routing block:

```python
                                transition_to_speaking = True
                                on_speaking_started()
```

becomes:

```python
                                transition_to_speaking = True
```

- [ ] **Step 8: Emit abs_start + audio in the routing block**

Replace the routing block (currently lines ~292-303):

```python
                # Route audio to pre-roll or pending_audio based on VAD state
                if vad_state == VADState.WAITING:
                    pre_roll.append(new_audio)
                else:  # SPEAKING
                    if transition_to_speaking and len(pre_roll) > 0:
                        pre_roll_audio = np.concatenate(list(pre_roll))
                        pending_audio = np.append(
                            pending_audio, np.concatenate([pre_roll_audio, new_audio])
                        )
                        pre_roll.clear()
                    else:
                        pending_audio = np.append(pending_audio, new_audio)
```

with:

```python
                # Route audio to pre-roll or pending_audio based on VAD state
                if vad_state == VADState.WAITING:
                    pre_roll.append(new_audio)
                    pre_roll_starts.append(chunk_start)
                else:  # SPEAKING
                    if transition_to_speaking and len(pre_roll) > 0:
                        utt_first_idx = pre_roll_starts[0]
                        pre_roll_audio = np.concatenate(list(pre_roll))
                        onset_audio = np.concatenate([pre_roll_audio, new_audio])
                        pending_audio = np.append(pending_audio, onset_audio)
                        pre_roll.clear()
                        pre_roll_starts.clear()
                        abs_start = (wall0 or time.time()) + utt_first_idx / sr
                        on_speaking_started(abs_start)
                        if on_audio is not None:
                            on_audio(onset_audio)
                    elif transition_to_speaking:
                        utt_first_idx = chunk_start
                        pending_audio = np.append(pending_audio, new_audio)
                        abs_start = (wall0 or time.time()) + utt_first_idx / sr
                        on_speaking_started(abs_start)
                        if on_audio is not None:
                            on_audio(new_audio)
                    else:
                        pending_audio = np.append(pending_audio, new_audio)
                        if on_audio is not None and len(new_audio):
                            on_audio(new_audio)
```

- [ ] **Step 9: Update the module's own `main()` default callback**

The CLI `main()` passes no callbacks, relying on defaults; the default `on_speaking_started` now takes `abs_start`. No change needed (the default lambda already accepts `abs_start`). Verify by importing:

Run: `conda run -n named-pipes python -c "from named_pipes.stt.voxtral.stream import stream_transcribe; import inspect; print('on_audio' in inspect.signature(stream_transcribe).parameters)"`
Expected: prints `True`

- [ ] **Step 10: Run the stream API tests**

Run: `conda run -n named-pipes python -m pytest tests/test_stt_voxtral_stream_api.py -q`
Expected: PASS (all, including the four new tests)

- [ ] **Step 11: Commit**

```bash
git add src/named_pipes/stt/voxtral/stream.py tests/test_stt_voxtral_stream_api.py
git commit -m "$(cat <<'EOF'
feat: add wall-clock anchor, abs_start, and on_audio callback to Voxtral stream

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Server wiring — config flags, audio accumulation, alignment jobs, words in `speech`

Wire the aligner into `STTServer`: opt-in config, per-utterance audio buffer, word-boundary triggering, a coalesced aligner, absolute conversion, and `speech` events with `words`. Graceful degradation when alignment is off or the model is unavailable.

**Files:**
- Modify: `src/named_pipes/stt/server.py`
- Test: `tests/test_stt_word_timestamps.py`

- [ ] **Step 1: Write the failing integration tests**

Create `tests/test_stt_word_timestamps.py`:

```python
"""Server integration tests for per-word timestamps using a fake aligner."""

import time

import numpy as np
import pytest

pytest.importorskip("mlx")

from named_pipes.stt import STTConfig, STTServer
from named_pipes.stt.alignment import WordTiming


class FakeAligner:
    """Returns one WordTiming per whitespace word; start=i, end=i+0.5 seconds."""

    def __init__(self):
        self.calls = []

    @property
    def available(self):
        return True

    def load(self):
        pass

    def align(self, audio, text):
        self.calls.append(text.strip())
        return [
            WordTiming(w, float(i), float(i) + 0.5)
            for i, w in enumerate(text.split())
        ]


def _spy_events(pipe):
    events = []
    pipe.send_event = lambda event, pid=None, **kw: events.append({"event": event, **kw})
    return events


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_align_disabled_emits_no_words():
    pipe = STTServer(STTConfig(name="stt-test"))
    try:
        assert pipe._coalescer is None
        events = _spy_events(pipe)
        pipe._on_start(1000.0)
        pipe._on_token(" hello")
        pipe._on_end()
        assert all("words" not in e for e in events)
    finally:
        pipe._close()


def test_align_enabled_emits_absolute_words_at_speech_end():
    fake = FakeAligner()
    pipe = STTServer(STTConfig(name="stt-test", align=True), aligner=fake)
    try:
        events = _spy_events(pipe)
        pipe._on_start(1000.0)
        pipe._on_audio(np.zeros(16000, dtype=np.float32))
        pipe._on_token(" hello")
        pipe._on_token(" world")
        pipe._on_end()  # enqueues final alignment over full utterance

        assert _wait_for(lambda: any("words" in e for e in events))
        worded = [e for e in events if "words" in e]
        final = worded[-1]
        assert final["text"].strip() == "hello world"
        assert final["words"][0] == {"word": "hello", "start": 1000.0, "end": 1000.5}
        assert final["words"][1] == {"word": "world", "start": 1001.0, "end": 1001.5}
    finally:
        pipe._close()


def test_word_boundary_triggers_incremental_alignment():
    fake = FakeAligner()
    pipe = STTServer(STTConfig(name="stt-test", align=True), aligner=fake)
    try:
        _spy_events(pipe)
        pipe._on_start(1000.0)
        pipe._on_audio(np.zeros(8000, dtype=np.float32))
        pipe._on_token(" hello")     # first word, no completed word yet
        pipe._on_token(" world")     # boundary: aligns completed "hello"
        assert _wait_for(lambda: "hello" in fake.calls)
    finally:
        pipe._close()


def test_align_error_degrades_without_words(monkeypatch):
    class BadAligner(FakeAligner):
        def align(self, audio, text):
            raise RuntimeError("model exploded")

    pipe = STTServer(STTConfig(name="stt-test", align=True), aligner=BadAligner())
    try:
        events = _spy_events(pipe)
        pipe._on_start(1000.0)
        pipe._on_audio(np.zeros(16000, dtype=np.float32))
        pipe._on_token(" hello")
        pipe._on_end()
        time.sleep(0.3)
        assert all("words" not in e for e in events)  # never crashes, no words
    finally:
        pipe._close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n named-pipes python -m pytest tests/test_stt_word_timestamps.py -q`
Expected: FAIL — `STTConfig` has no `align` field / `STTServer.__init__` has no `aligner` param / `_coalescer` missing.

- [ ] **Step 3: Add config fields and imports**

In `src/named_pipes/stt/server.py`, update the imports near the top (after `import sounddevice as sd`):

```python
import numpy as np
import sounddevice as sd
from pydantic import BaseModel

from named_pipes.stt.alignment import (
    CoalescingAligner,
    detect_word_boundary,
    to_absolute,
)
from named_pipes.stt.voxtral.stream import stream_transcribe
from named_pipes.tools.server import ToolServer, ToolState
```

Add fields to `STTConfig`:

```python
class STTConfig(BaseModel):
    name: str = "stt"
    description: str = "👂 Real-time speech-to-text server over a named pipe."
    model_path: str = "mlx-community/Voxtral-Mini-4B-Realtime-6bit"
    temperature: float = 0.0
    vad_onset: int = 2
    vad_offset: int = 32
    device: int | None = None
    align: bool = False
    align_language: str = "English"
    align_model: str = "mlx-community/Qwen3-ForcedAligner-0.6B-4bit"
    verbose: bool = True
```

- [ ] **Step 4: Initialise alignment state in `__init__`**

Change the `STTServer.__init__` signature and add alignment setup. Replace:

```python
    def __init__(self, config: STTConfig = STTConfig()):
        super().__init__(config.name, description=config.description)
        self._config = config
        self._device = config.device
        self._current_text = ""
        self._broadcast_lock = threading.Lock()
        self._stop_event: threading.Event | None = None
        self._worker: threading.Thread | None = None

        self.set_state(STTState.READY)
```

with:

```python
    def __init__(self, config: STTConfig = STTConfig(), aligner=None):
        super().__init__(config.name, description=config.description)
        self._config = config
        self._device = config.device
        self._current_text = ""
        self._broadcast_lock = threading.Lock()
        self._stop_event: threading.Event | None = None
        self._worker: threading.Thread | None = None

        # Per-utterance forced-alignment state.
        self._utt_audio = np.zeros(0, dtype=np.float32)
        self._utt_abs_start = 0.0
        self._coalescer = None
        if config.align:
            if aligner is None:
                from named_pipes.stt.aligner import ForcedAligner

                aligner = ForcedAligner(config.align_model, config.align_language)
            self._aligner = aligner
            self._coalescer = CoalescingAligner(
                align_fn=self._aligner.align,
                emit_fn=self._emit_words,
                on_error=self._on_align_error,
            )

        self.set_state(STTState.READY)
```

- [ ] **Step 5: Pass `on_audio` to the worker**

In `_handle_start`, add `on_audio` to the `kwargs` dict passed to `stream_transcribe` (alongside the existing `on_ready`):

```python
                "on_ready": self._on_ready,
                "on_audio": self._on_audio,
                "stop_event": self._stop_event,
```

- [ ] **Step 6: Update the worker callbacks**

Replace the callbacks section (`_on_ready`, `_on_token`, `_on_start`, `_on_end`):

```python
    def _on_ready(self) -> None:
        self.set_state(STTState.LISTENING)

    def _on_token(self, text: str) -> None:
        if self._coalescer is not None and detect_word_boundary(self._current_text, text):
            if self._current_text.strip():
                self._coalescer.submit(
                    self._utt_audio.copy(), self._current_text, self._utt_abs_start
                )
        self._current_text += text
        with self._broadcast_lock:
            self.send_event("token", text=text)
            self.send_event("speech", text=self._current_text)

    def _on_start(self, abs_start: float = 0.0) -> None:
        self._current_text = ""
        self._utt_audio = np.zeros(0, dtype=np.float32)
        self._utt_abs_start = abs_start
        self.set_state(STTState.TRANSCRIBING)
        with self._broadcast_lock:
            self.send_event("speech_start")

    def _on_audio(self, chunk) -> None:
        if self._coalescer is not None:
            self._utt_audio = np.append(self._utt_audio, chunk)

    def _on_end(self) -> None:
        with self._broadcast_lock:
            self.send_event("speech_end")
        if self._coalescer is not None and self._current_text.strip():
            self._coalescer.submit(
                self._utt_audio.copy(), self._current_text, self._utt_abs_start
            )
        if self._state is STTState.TRANSCRIBING:
            self.set_state(STTState.LISTENING)

    def _emit_words(self, items, text: str, abs_start: float) -> None:
        words = to_absolute(items, abs_start)
        with self._broadcast_lock:
            self.send_event("speech", text=text, words=words)

    def _on_align_error(self, exc: Exception) -> None:
        if self._config.verbose:
            print(f"[STT] alignment error: {exc}", flush=True)
```

- [ ] **Step 7: Stop the coalescer in `_close`**

Replace `_close`:

```python
    def _close(self):
        # moonshine_voice's stop()/close() aren't idempotent, and __del__
        # calls _close() again after an explicit close — guard accordingly.
        if self._closed:
            return
        if self._coalescer is not None:
            self._coalescer.stop()
        if self._stop_event is not None:
            self._stop_event.set()
        if self._worker is not None:
            self._worker.join(timeout=5)
        super()._close()
```

> Note: the existing `_close` body in `server.py` joins the worker and calls `super()._close()`; keep those lines and just add the coalescer stop and the `_closed` guard if not already present.

- [ ] **Step 8: Run the integration tests**

Run: `conda run -n named-pipes python -m pytest tests/test_stt_word_timestamps.py -q`
Expected: PASS (4 passed)

- [ ] **Step 9: Re-run the repaired server test from Task 1 (now fully green)**

Run: `conda run -n named-pipes python -m pytest tests/test_stt_named_pipe.py -q`
Expected: PASS (all) — `_on_start(1000.0)` now matches the new signature.

- [ ] **Step 10: Commit**

```bash
git add src/named_pipes/stt/server.py tests/test_stt_word_timestamps.py
git commit -m "$(cat <<'EOF'
feat: emit per-word absolute timestamps in STT speech events via forced aligner

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Interface field, example client, and docs

Advertise the `words` field in the `speech` interface, print it in the example client, and document the opt-in config + model download.

**Files:**
- Modify: `src/named_pipes/interfaces/stt.py`
- Modify: `src/examples/stt_client.py`
- Modify: `src/named_pipes/stt/README.md`
- Test: `tests/test_stt_interface.py`

- [ ] **Step 1: Write the failing interface test**

Create `tests/test_stt_interface.py`:

```python
"""The STT interface advertises the per-word `words` field on `speech` (CI-runnable)."""

from named_pipes.interfaces.stt import STT


def test_speech_event_has_words_field():
    speech = next(e for e in STT.events if e.name == "speech")
    field_names = {f.name for f in speech.fields}
    assert "words" in field_names
    words = next(f for f in speech.fields if f.name == "words")
    assert words.type == "list"
    assert words.required is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n named-pipes python -m pytest tests/test_stt_interface.py -q`
Expected: FAIL — `StopIteration`/assert: no `words` field.

- [ ] **Step 3: Add the `words` field to the `speech` EventSpec**

In `src/named_pipes/interfaces/stt.py`, replace the `speech` event:

```python
        EventSpec(
            name="speech",
            description="Broadcast when the current speech utterance has an update.",
            fields=[
                ArgSpec(
                    name="text",
                    description="Updated transcription of the current utterance.",
                )
            ],
        ),
```

with:

```python
        EventSpec(
            name="speech",
            description="Broadcast when the current speech utterance has an update.",
            fields=[
                ArgSpec(
                    name="text",
                    description="Updated transcription of the current utterance.",
                ),
                ArgSpec(
                    name="words",
                    type="list",
                    required=False,
                    description=(
                        "Per-word timestamps when forced alignment is enabled: list of "
                        "{word, start, end} with absolute Unix epoch seconds (ms precision)."
                    ),
                ),
            ],
        ),
```

- [ ] **Step 4: Run the interface test**

Run: `conda run -n named-pipes python -m pytest tests/test_stt_interface.py -q`
Expected: PASS

- [ ] **Step 5: Print word timings in the example client**

In `src/examples/stt_client.py`, replace the `speech` handler:

```python
        @client.on("speech")
        def _(msg):
            printer.overwrite(msg.get("text", ""))
```

with:

```python
        @client.on("speech")
        def _(msg):
            printer.overwrite(msg.get("text", ""))
            words = msg.get("words")
            if words:
                printer.newline()
                for w in words:
                    print(f"  [{w['start']:.3f}–{w['end']:.3f}] {w['word']}")
```

- [ ] **Step 6: Verify the example client still imports/compiles**

Run: `conda run -n named-pipes python -m py_compile src/examples/stt_client.py && echo OK`
Expected: prints `OK`

- [ ] **Step 7: Document the feature**

In `src/named_pipes/stt/README.md`, under the `STTConfig` table add rows for the new fields, and add this section after the **Wire Example** section:

```markdown
## Per-word timestamps (forced alignment)

Set `align=True` to attach per-word absolute timestamps to `speech` events. The
server re-aligns the utterance-so-far on each word boundary (coalesced, in a
background thread) plus once at `speech_end`, using the MLX
`mlx-community/Qwen3-ForcedAligner-0.6B-4bit` model via `mlx-audio`.

Download the aligner model once:

    hf download mlx-community/Qwen3-ForcedAligner-0.6B-4bit

`speech` events then include a `words` array:

    {"event": "speech", "text": "hello world",
     "words": [{"word": "hello", "start": 1750540000.080, "end": 1750540000.480},
               {"word": "world", "start": 1750540000.560, "end": 1750540000.800}]}

`start`/`end` are absolute Unix epoch seconds (millisecond precision). The
aligner's intrinsic resolution is 80 ms. If alignment is disabled or the model
is unavailable, `speech` events are emitted without `words` and transcription is
unaffected.
```

Also add to the `STTConfig` field table:

```markdown
| `align` | `bool` | `False` | Attach per-word forced-alignment timestamps to `speech` events |
| `align_language` | `str` | `"English"` | Language passed to the forced aligner |
| `align_model` | `str` | `"mlx-community/Qwen3-ForcedAligner-0.6B-4bit"` | MLX forced-aligner model id |
```

- [ ] **Step 8: Run the whole Python suite**

Run: `conda run -n named-pipes python -m pytest tests/ -q`
Expected: PASS or SKIP for every test (model-gated/aligner integration may SKIP if the model is not downloaded). No failures, no collection errors.

- [ ] **Step 9: Lint**

Run: `conda run -n named-pipes python -m ruff check src/named_pipes/stt tests/test_stt_alignment.py tests/test_stt_word_timestamps.py tests/test_stt_forced_aligner.py tests/test_stt_interface.py`
Expected: no errors (fix any unused imports the linter flags).

- [ ] **Step 10: Commit**

```bash
git add src/named_pipes/interfaces/stt.py src/examples/stt_client.py src/named_pipes/stt/README.md tests/test_stt_interface.py
git commit -m "$(cat <<'EOF'
feat: advertise speech `words` field; print word timings in example; document align

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes (for the implementer)

- **Spec coverage:** trigger strategy (Task 6 boundary + final), opt-in `align` (Task 6), absolute ms timestamps (Task 2 `to_absolute`, Task 6 wiring), sample-accurate anchor (Task 5), `aligner.py` isolation + injectability (Tasks 4/6), `words` interface field (Task 7), graceful degradation (Task 6 `_on_align_error` + `CoalescingAligner` try/except), CI-runnable pure tests (Tasks 2/3/7), Mac-gated integration (Tasks 4/5/6), docs (Task 7). The MLX cross-thread risk is exercised on Mac via Task 6; if instability appears, the spec's documented fallback is subprocess isolation (not built here).
- **Type consistency:** `WordTiming(word, start, end)`; `CoalescingAligner.submit(audio, text, abs_start)` → `emit_fn(items, text, abs_start)`; `ForcedAligner.align(audio, text) -> list[WordTiming]`; `to_absolute(items, abs_start) -> list[dict]` with keys `word/start/end`. These match across Tasks 2–7.
- **Audio units:** every audio array is 16 kHz mono float32 (Voxtral capture and aligner expectation).
```
