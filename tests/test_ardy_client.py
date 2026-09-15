"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

End-to-end tests for named_pipes.ardy.ArdyClient.

These run against real FIFOs and a stub server subprocess
(src/examples/ardy_stub_server.py), so they cover the transport, the req_id
correlation and the tensor codec together. No model is loaded.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from named_pipes.ardy import (
    ArdyClient,
    ArdyError,
    ArdySession,
    ArdyTimeout,
    decode_tensor,
    encode_tensor,
)

PIPE = "/tmp/tool-ardy"
STUB = Path(__file__).resolve().parents[1] / "src" / "examples" / "ardy_stub_server.py"


@pytest.fixture(scope="module")
def stub_server():
    """Run the stub ARDY server for the duration of the module."""
    for leftover in Path("/tmp").glob("tool-ardy*"):
        try:
            leftover.unlink()
        except OSError:
            pass

    proc = subprocess.Popen(
        [sys.executable, "-u", str(STUB)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 15
    while time.time() < deadline:
        if os.path.exists(PIPE):
            break
        if proc.poll() is not None:
            out = proc.stdout.read().decode() if proc.stdout else ""
            pytest.fail(f"stub server exited early:\n{out}")
        time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail(f"stub server never created {PIPE}")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def client(stub_server):
    with ArdyClient(timeout=10.0) as c:
        yield c


# ---------------------------------------------------------------------------
# TestTensorCodec — no server needed
# ---------------------------------------------------------------------------


class TestTensorCodec:
    def test_float32_round_trip(self):
        a = np.random.randn(2, 3, 4).astype(np.float32)
        np.testing.assert_array_equal(decode_tensor(encode_tensor(a)), a)

    def test_float64_narrows_to_float32(self):
        a = np.random.randn(2, 3)
        out = decode_tensor(encode_tensor(a))
        assert out.dtype == np.float32
        np.testing.assert_allclose(out, a.astype(np.float32))

    def test_bool_dtype_is_preserved(self):
        m = np.array([[True, False, True]])
        out = decode_tensor(encode_tensor(m))
        assert out.dtype == np.bool_
        np.testing.assert_array_equal(out, m)

    def test_shape_is_preserved(self):
        a = np.zeros((1, 10, 148), np.float32)
        assert decode_tensor(encode_tensor(a)).shape == (1, 10, 148)

    def test_decode_passes_none_through(self):
        assert decode_tensor(None) is None

    def test_unsupported_dtype_rejected(self):
        with pytest.raises(ValueError):
            encode_tensor(np.zeros(3, dtype=np.complex64))


# ---------------------------------------------------------------------------
# TestSessionState — client-owned, no server needed
# ---------------------------------------------------------------------------


class TestSessionState:
    def test_empty_session(self):
        s = ArdySession()
        assert s.num_tokens == 0
        assert s.history_window(4) is None

    def test_append_accumulates_tokens_and_frames(self):
        s = ArdySession()
        tokens = np.zeros((1, 10, 148), np.float32)
        s.append_tokens(tokens, frames_per_token=4)
        s.append_tokens(tokens, frames_per_token=4)
        assert s.num_tokens == 20
        assert s.frames_emitted == 80

    def test_history_window_takes_most_recent(self):
        s = ArdySession()
        s.append_tokens(np.arange(10, dtype=np.float32).reshape(1, 10, 1), 4)
        window = s.history_window(3)
        assert window.shape == (1, 3, 1)
        np.testing.assert_array_equal(window[0, :, 0], [7, 8, 9])

    def test_history_window_none_means_everything(self):
        s = ArdySession()
        s.append_tokens(np.zeros((1, 10, 1), np.float32), 4)
        assert s.history_window(None).shape == (1, 10, 1)

    def test_reset_clears_motion(self):
        s = ArdySession()
        s.append_tokens(np.zeros((1, 10, 148), np.float32), 4)
        s.text_feat = np.zeros((1, 1, 4096), np.float32)
        s.reset()
        assert s.num_tokens == 0 and s.frames_emitted == 0
        assert s.text_feat is not None, "reset keeps prompt conditioning"


# ---------------------------------------------------------------------------
# TestCommands — against the stub server
# ---------------------------------------------------------------------------


class TestCommands:
    def test_model_info(self, client):
        info = client.model_info()
        assert info.model_name == "ARDY-Core-RP-20FPS-Horizon40"
        assert info.token_dim == 148  # 20 root + 128 latent
        assert info.num_generation_tokens == 10  # 40 frames / 4 per token
        assert info.horizon_seconds == pytest.approx(2.0)

    def test_model_info_is_cached(self, client):
        assert client.model_info() is client.model_info()

    def test_model_info_refresh_refetches(self, client):
        first = client.model_info()
        assert client.model_info(refresh=True) is not first

    def test_tokenize(self, client):
        tokens = client.tokenize(np.zeros((1, 40, 272), np.float32))
        assert tokens.shape == (1, 10, 148)

    def test_detokenize(self, client):
        motion = client.detokenize(np.zeros((1, 10, 148), np.float32))
        assert motion.shape == (1, 40, 272)

    def test_requantize(self, client):
        out = client.requantize(np.array([[[0.4, 1.6]]], np.float32))
        np.testing.assert_allclose(out, [[[0.0, 2.0]]])


# ---------------------------------------------------------------------------
# TestDenoise
# ---------------------------------------------------------------------------


def _masks(num_tokens, history_tokens):
    gen = np.zeros((1, num_tokens), dtype=bool)
    gen[:, history_tokens:] = True
    return {
        "generation_token_mask": gen,
        "history_len": history_tokens * 4,
        "generation_len": (num_tokens - history_tokens) * 4,
        "future_len": 0,
    }


def _cond():
    return {
        "text_feat": np.zeros((1, 1, 4096), np.float32),
        "text_pad_mask": np.ones((1, 1), bool),
        "first_heading_angle": np.zeros(1, np.float32),
    }


class TestDenoise:
    def test_history_passes_through_untouched(self, client):
        x = np.ones((1, 12, 148), np.float32)
        out = client.denoise(x, t=99, num_denoising_steps=100,
                             masks=_masks(12, 2), cfg_weight=(2.0, 2.0), **_cond())
        np.testing.assert_array_equal(out[0, :2], np.ones((2, 148), np.float32))

    def test_generation_tokens_are_stepped(self, client):
        x = np.ones((1, 12, 148), np.float32)
        out = client.denoise(x, t=99, num_denoising_steps=100,
                             masks=_masks(12, 2), **_cond())
        assert np.allclose(out[0, 2:], 0.5)

    def test_scalar_cfg_weight_accepted(self, client):
        x = np.ones((1, 12, 148), np.float32)
        out = client.denoise(x, t=0, num_denoising_steps=1,
                             masks=_masks(12, 2), cfg_weight=2.5, **_cond())
        assert out.shape == x.shape

    def test_denoise_loop_runs_every_step(self, client):
        x = np.ones((1, 12, 148), np.float32)
        out = client.denoise_loop(x, 4, masks=_masks(12, 2), **_cond())
        assert np.allclose(out[0, 2:], 0.5**4)
        np.testing.assert_array_equal(out[0, :2], np.ones((2, 148), np.float32))

    def test_denoise_loop_reports_progress(self, client):
        seen = []
        client.denoise_loop(np.ones((1, 12, 148), np.float32), 3,
                            progress=lambda i, n: seen.append((i, n)),
                            masks=_masks(12, 2), **_cond())
        assert seen == [(1, 3), (2, 3), (3, 3)]


# ---------------------------------------------------------------------------
# TestFailureModes
# ---------------------------------------------------------------------------


class TestFailureModes:
    def test_error_event_raises(self, client):
        with pytest.raises(ArdyError, match="deliberate failure"):
            client._request("boom")

    def test_unanswered_command_times_out(self, client):
        with pytest.raises(ArdyTimeout):
            client._request("no_such_command", timeout=1.0)

    def test_client_still_usable_after_a_timeout(self, client):
        with pytest.raises(ArdyTimeout):
            client._request("no_such_command", timeout=1.0)
        assert client.model_info(refresh=True).token_dim == 148


# ---------------------------------------------------------------------------
# TestMultipleSessions — the point of client-owned state
# ---------------------------------------------------------------------------


class TestMultipleSessions:
    def test_sessions_are_independent(self, client):
        hero = client.new_session("hero")
        npc = client.new_session("npc")
        hero.append_tokens(np.zeros((1, 10, 148), np.float32), 4)
        assert hero.num_tokens == 10
        assert npc.num_tokens == 0

    def test_session_is_created_on_first_use(self, client):
        s = client.session("lazily_made")
        assert isinstance(s, ArdySession)
        assert client.session("lazily_made") is s

    def test_new_session_replaces_an_existing_one(self, client):
        first = client.new_session("hero")
        first.append_tokens(np.zeros((1, 10, 148), np.float32), 4)
        assert client.new_session("hero").num_tokens == 0
