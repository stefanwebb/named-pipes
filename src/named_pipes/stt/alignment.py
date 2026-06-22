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
