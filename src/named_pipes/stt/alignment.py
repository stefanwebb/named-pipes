"""© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

Pure helpers for forced-alignment word timestamps. No MLX / heavy imports, so
this module is unit-testable in CI.
"""

import threading
from dataclasses import dataclass
from typing import Callable, Optional


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
