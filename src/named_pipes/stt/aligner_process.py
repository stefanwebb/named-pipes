"""© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

Out-of-process forced alignment.

The MLX forced-aligner model cannot share a process with the Voxtral streaming
decoder: both drive Metal, and running ``mx.eval`` from two threads of one
process concurrently (decoder thread + aligner thread) deadlocks the Metal
command queue, hanging the whole STT server. ``SubprocessAligner`` runs the real
``ForcedAligner`` in a ``spawn`` child so alignment gets its own, isolated Metal
context — no MLX runs in the server process for alignment at all.

This module imports no MLX at module scope (the heavy ``ForcedAligner`` import
lives inside ``_default_factory``), so the worker loop stays unit-testable in CI
and the module re-imports cheaply inside the spawn child.
"""

import multiprocessing as mp
import queue
import threading
from typing import Callable, Optional

import numpy as np

from named_pipes.stt.alignment import WordTiming

# A request is ``(audio, text)`` to align, ``WARM`` to eagerly load the model,
# or ``None`` to shut down. A response is ``("ok", [(word, start, end), ...])``
# or ``("err", repr_str)``; ``WARM`` is fire-and-forget and yields no response.
WARM = "warm"  # plain str so it survives pickling across the spawn boundary


def _default_factory(model_id: str, language: str):
    from named_pipes.stt.aligner import ForcedAligner

    return ForcedAligner(model_id, language)


class _FailedAligner:
    """Stand-in whose ``align`` re-raises the construction error per job, so a
    child that can't load its model degrades gracefully instead of hanging the
    parent's blocking ``align`` call."""

    def __init__(self, exc: Exception):
        self._exc = exc

    def align(self, audio, text):
        raise self._exc


def run_alignment_worker(aligner, requests, responses) -> None:
    """Consume ``(audio, text)`` jobs, align, push results until the sentinel.

    Pure with respect to the queue types — any object with ``get``/``put`` works,
    so this loop is exercised in-process with ``queue.Queue`` in tests and with
    ``multiprocessing.Queue`` in the spawn child.
    """
    while True:
        job = requests.get()
        if job is None:
            return
        if job == WARM:
            load = getattr(aligner, "load", None)
            if callable(load):
                try:
                    load()
                except Exception:  # noqa: BLE001 - a real align will surface it
                    pass
            continue
        audio, text = job
        try:
            items = aligner.align(audio, text)
            responses.put(("ok", [(w.word, w.start, w.end) for w in items]))
        except Exception as exc:  # noqa: BLE001 - forward, never kill the worker
            responses.put(("err", repr(exc)))


def _worker_main(model_id, language, factory, requests, responses) -> None:
    factory = factory or _default_factory
    try:
        aligner = factory(model_id, language)
    except Exception as exc:  # noqa: BLE001 - degrade; report on every job
        aligner = _FailedAligner(exc)
    run_alignment_worker(aligner, requests, responses)


class SubprocessAligner:
    """Drop-in for ``ForcedAligner`` that runs alignment in a ``spawn`` child.

    Exposes the same ``align(audio, text) -> list[WordTiming]`` interface, so it
    plugs straight into ``CoalescingAligner``. The child is spawned lazily on the
    first ``align`` and reused thereafter; ``stop`` shuts it down.
    """

    def __init__(
        self,
        model_id: str,
        language: str = "English",
        factory: Optional[Callable[[str, str], object]] = None,
        timeout: float = 120.0,
    ):
        self._model_id = model_id
        self._language = language
        self._factory = factory
        self._timeout = timeout
        self._ctx = mp.get_context("spawn")
        self._proc = None
        self._requests = None
        self._responses = None
        self._lock = threading.Lock()

    def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.is_alive():
            return
        self._requests = self._ctx.Queue()
        self._responses = self._ctx.Queue()
        self._proc = self._ctx.Process(
            target=_worker_main,
            args=(
                self._model_id,
                self._language,
                self._factory,
                self._requests,
                self._responses,
            ),
            name="stt-aligner-proc",
            daemon=True,
        )
        self._proc.start()

    def warm(self) -> None:
        """Spawn the child and trigger model loading without blocking, so the
        first real ``align`` doesn't pay the load latency. Fire-and-forget."""
        with self._lock:
            self._ensure_started()
            requests = self._requests
        requests.put(WARM)

    def align(self, audio: np.ndarray, text: str) -> list[WordTiming]:
        with self._lock:
            self._ensure_started()
            requests, responses = self._requests, self._responses
        requests.put((np.asarray(audio, dtype=np.float32), text))
        try:
            status, payload = responses.get(timeout=self._timeout)
        except queue.Empty:
            raise RuntimeError("alignment subprocess timed out") from None
        if status == "err":
            raise RuntimeError(payload)
        return [WordTiming(word, start, end) for (word, start, end) in payload]

    def stop(self) -> None:
        with self._lock:
            proc, requests = self._proc, self._requests
            self._proc = self._requests = self._responses = None
        if proc is None:
            return
        try:
            requests.put(None)
        except Exception:  # noqa: BLE001 - best-effort graceful stop
            pass
        proc.join(timeout=5)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=2)
