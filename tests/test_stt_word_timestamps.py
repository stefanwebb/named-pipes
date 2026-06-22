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
