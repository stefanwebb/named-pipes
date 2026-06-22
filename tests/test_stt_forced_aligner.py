"""Tests for the MLX ForcedAligner wrapper (Mac-only; model test is gated)."""

import os

import numpy as np
import pytest

pytest.importorskip("mlx_audio")

from named_pipes.stt.aligner import DEFAULT_ALIGN_MODEL, ForcedAligner
from named_pipes.stt.alignment import WordTiming


def _hf_cache_dir() -> str:
    return (
        os.environ.get("HF_HUB_CACHE")
        or os.environ.get("HUGGINGFACE_HUB_CACHE")
        or os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    )


def _model_cached(model_id: str) -> bool:
    model_dir = model_id.replace("/", "--")
    return os.path.isdir(os.path.join(_hf_cache_dir(), f"models--{model_dir}"))


def test_available_is_false_before_load():
    aligner = ForcedAligner()
    assert aligner.available is False


def test_load_failure_sets_failed(monkeypatch):
    aligner = ForcedAligner(model_id="does-not-exist/nope")

    def boom(*a, **k):
        raise RuntimeError("no such model")

    monkeypatch.setattr("mlx_audio.stt.utils.load_model", boom)
    with pytest.raises(RuntimeError):
        aligner.load()
    assert aligner.available is False


@pytest.mark.skipif(
    not _model_cached(DEFAULT_ALIGN_MODEL),
    reason=f"aligner model {DEFAULT_ALIGN_MODEL} not downloaded (hf download {DEFAULT_ALIGN_MODEL})",
)
def test_align_returns_word_timings():
    aligner = ForcedAligner()
    aligner.load()
    assert aligner.available is True
    # 1.5 s of low-level noise; we assert structure, not transcription accuracy.
    rng = np.random.default_rng(0)
    audio = (rng.standard_normal(int(1.5 * 16000)).astype(np.float32)) * 0.01
    result = aligner.align(audio, "hello world")
    assert isinstance(result, list)
    assert all(isinstance(w, WordTiming) for w in result)
    for w in result:
        assert w.start <= w.end
