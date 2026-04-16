"""Verifies voxmlx source files are vendored into named_pipes.stt.voxtral and importable."""

import pytest

pytest.importorskip("mlx")


def test_voxtral_subpackage_importable():
    from named_pipes.stt.voxtral.stream import stream_transcribe  # noqa: F401


def test_all_voxtral_modules_importable():
    import importlib

    for name in [
        "audio",
        "cache",
        "convert",
        "encoder",
        "generate",
        "language_model",
        "model",
        "stream",
        "weights",
    ]:
        importlib.import_module(f"named_pipes.stt.voxtral.{name}")
