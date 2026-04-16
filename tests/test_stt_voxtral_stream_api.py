"""Verifies the additive parameters on stream_transcribe."""

import inspect

import pytest

pytest.importorskip("mlx")

from named_pipes.stt.voxtral.stream import stream_transcribe


def test_stream_transcribe_has_on_token_kwarg():
    sig = inspect.signature(stream_transcribe)
    assert "on_token" in sig.parameters
    assert sig.parameters["on_token"].default is None


def test_stream_transcribe_source_routes_tokens_through_on_token():
    src = inspect.getsource(stream_transcribe)
    assert "on_token(text)" in src
    assert 'print(text, end=""' in src


def test_stream_transcribe_has_stop_event_kwarg():
    sig = inspect.signature(stream_transcribe)
    assert "stop_event" in sig.parameters
    assert sig.parameters["stop_event"].default is None


def test_stream_transcribe_source_checks_stop_event():
    src = inspect.getsource(stream_transcribe)
    assert "stop_event" in src
    assert "is_set()" in src
