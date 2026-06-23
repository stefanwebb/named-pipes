"""Tests for the out-of-process forced aligner.

These do NOT require MLX: the worker loop is exercised in-process with a fake
aligner, and the real spawn round-trip uses importable dummy factories so the
child process never touches the heavy model. No ``pytest.importorskip`` at
module scope, so the test module re-imports cleanly inside the spawn child.
"""

import queue

import numpy as np

from named_pipes.stt.aligner_process import (
    WARM,
    SubprocessAligner,
    run_alignment_worker,
)
from named_pipes.stt.alignment import WordTiming


# --- Module-level dummies (must be importable for multiprocessing spawn) ------


class _EchoAligner:
    """One WordTiming per whitespace word; start=i, end=i+0.5 (no model)."""

    def align(self, audio, text):
        return [
            WordTiming(w, float(i), float(i) + 0.5) for i, w in enumerate(text.split())
        ]


def _echo_factory(model_id, language):
    return _EchoAligner()


def _boom_factory(model_id, language):
    raise RuntimeError("cannot load model")


# --- Worker loop (in-process, no subprocess) ----------------------------------


def test_worker_loop_serializes_word_timings():
    requests: queue.Queue = queue.Queue()
    responses: queue.Queue = queue.Queue()
    requests.put((np.zeros(16000, dtype=np.float32), "hello world"))
    requests.put(None)

    run_alignment_worker(_EchoAligner(), requests, responses)

    status, payload = responses.get_nowait()
    assert status == "ok"
    assert payload == [("hello", 0.0, 0.5), ("world", 1.0, 1.5)]


def test_worker_loop_reports_errors_and_keeps_running():
    class _Bad:
        def align(self, audio, text):
            raise RuntimeError("boom")

    requests: queue.Queue = queue.Queue()
    responses: queue.Queue = queue.Queue()
    requests.put((np.zeros(8000, dtype=np.float32), "a"))
    requests.put((np.zeros(8000, dtype=np.float32), "b"))
    requests.put(None)

    run_alignment_worker(_Bad(), requests, responses)

    first = responses.get_nowait()
    second = responses.get_nowait()
    assert first[0] == "err" and "boom" in first[1]
    assert second[0] == "err"  # did not die after the first error


def test_worker_loop_warms_model_on_warm_request():
    class _Loadable:
        def __init__(self):
            self.loaded = False

        def load(self):
            self.loaded = True

        def align(self, audio, text):
            return []

    aligner = _Loadable()
    requests: queue.Queue = queue.Queue()
    responses: queue.Queue = queue.Queue()
    requests.put(WARM)
    requests.put(None)

    run_alignment_worker(aligner, requests, responses)

    assert aligner.loaded is True
    assert responses.empty()  # warm is fire-and-forget: no response


# --- Real spawn round-trip ----------------------------------------------------


def test_subprocess_aligner_round_trip():
    aligner = SubprocessAligner("unused-model", factory=_echo_factory)
    try:
        result = aligner.align(np.zeros(16000, dtype=np.float32), "hello world")
        assert all(isinstance(w, WordTiming) for w in result)
        assert [(w.word, w.start, w.end) for w in result] == [
            ("hello", 0.0, 0.5),
            ("world", 1.0, 1.5),
        ]
    finally:
        aligner.stop()


def test_subprocess_aligner_degrades_on_factory_failure():
    aligner = SubprocessAligner("unused-model", factory=_boom_factory)
    try:
        with np.testing.assert_raises(RuntimeError):
            aligner.align(np.zeros(8000, dtype=np.float32), "hello")
    finally:
        aligner.stop()


def test_warm_starts_child_without_aligning():
    aligner = SubprocessAligner("unused-model", factory=_echo_factory)
    try:
        assert aligner._proc is None
        aligner.warm()
        proc = aligner._proc
        assert proc is not None and proc.is_alive()
    finally:
        aligner.stop()


def test_stop_is_idempotent_and_terminates_child():
    aligner = SubprocessAligner("unused-model", factory=_echo_factory)
    aligner.align(np.zeros(1600, dtype=np.float32), "hi")
    proc = aligner._proc
    assert proc is not None and proc.is_alive()
    aligner.stop()
    assert not proc.is_alive()
    aligner.stop()  # idempotent — no raise
