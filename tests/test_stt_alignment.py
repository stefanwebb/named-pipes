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
