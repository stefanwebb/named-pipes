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
            WordTiming(w, float(i), float(i) + 0.5) for i, w in enumerate(text.split())
        ]


class WarmingAligner(FakeAligner):
    """FakeAligner that also records eager-warm calls."""

    def __init__(self):
        super().__init__()
        self.warmed = False

    def warm(self):
        self.warmed = True


def _spy_events(pipe):
    events = []
    pipe.send_event = lambda event, pid=None, **kw: events.append(
        {"event": event, **kw}
    )
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

        # Wait for the FINAL full-utterance alignment specifically: the
        # incremental "hello" alignment may emit first, so waiting for "any
        # words" then reading the last event would race the final job.
        def _final_emitted():
            return any(
                "words" in e and e["text"].strip() == "hello world" for e in events
            )

        assert _wait_for(_final_emitted)
        final = [
            e for e in events if "words" in e and e["text"].strip() == "hello world"
        ][-1]
        assert final["words"][0] == {"word": "hello", "start": 1000.0, "end": 1000.5}
        assert final["words"][1] == {"word": "world", "start": 1001.0, "end": 1001.5}
    finally:
        pipe._close()


def test_start_eagerly_warms_aligner(monkeypatch):
    monkeypatch.setattr("named_pipes.stt.server.stream_transcribe", lambda **kw: None)
    fake = WarmingAligner()
    pipe = STTServer(STTConfig(name="stt-test", align=True), aligner=fake)
    try:
        pipe._handle_start({}, None)
        assert _wait_for(lambda: fake.warmed)
    finally:
        pipe._close()


def test_start_without_align_does_not_warm(monkeypatch):
    monkeypatch.setattr("named_pipes.stt.server.stream_transcribe", lambda **kw: None)
    pipe = STTServer(STTConfig(name="stt-test"))
    try:
        pipe._handle_start({}, None)  # must not raise without an aligner
        assert pipe._aligner is None
    finally:
        pipe._close()


def test_word_boundary_triggers_incremental_alignment():
    fake = FakeAligner()
    pipe = STTServer(STTConfig(name="stt-test", align=True), aligner=fake)
    try:
        _spy_events(pipe)
        pipe._on_start(1000.0)
        pipe._on_audio(np.zeros(8000, dtype=np.float32))
        pipe._on_token(" hello")  # first word, no completed word yet
        pipe._on_token(" world")  # boundary: aligns completed "hello"
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
