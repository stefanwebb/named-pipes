"""Pure-logic tests for STT forced-alignment helpers (no mlx, runs in CI)."""

import threading
import time

from named_pipes.stt.alignment import (
    CoalescingAligner,
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


def test_runs_submitted_job_and_emits():
    emits = []
    ca = CoalescingAligner(
        align_fn=lambda audio, text: [WordTiming(text, 0.0, 0.5)],
        emit_fn=lambda items, text, abs_start: emits.append(
            (items[0].word, text, abs_start)
        ),
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
    assert started.wait(2.0)  # "A" is running
    ca.submit("b", "B", 2.0)  # queued
    ca.submit("c", "C", 3.0)  # overwrites "B"
    release.set()
    deadline = time.monotonic() + 2.0
    while len(emits) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    ca.stop()
    assert calls == ["A", "C"]  # "B" coalesced away
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
    ca.stop()  # must process the pending job before exiting
    assert emits == ["final"]
