"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

ArdyClient — client side of the ``ardy`` interface (see
``named_pipes.interfaces.ardy``).

The server is a stateless evaluator: it holds the weights and answers
``tokenize`` / ``detokenize`` / ``requantize`` / ``denoise``. **This client owns
the session state** — the hybrid history tokens, the accumulated world
translation and the first-frame heading — and drives the denoising loop itself.

That split means the server can be restarted, shared between clients, or
replaced without losing a take, and a client can keep several independent
characters in flight against one loaded model.
"""

import base64
import itertools
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np

from named_pipes.tools.client import ToolClient

__all__ = [
    "ArdyClient",
    "ArdyError",
    "ArdySession",
    "ArdyTimeout",
    "ModelInfo",
    "decode_tensor",
    "encode_tensor",
]

DEFAULT_TIMEOUT = 60.0

# dtypes accepted on the wire; anything else must be cast by the caller
_ALLOWED_DTYPES = {"float32", "float64", "int64", "int32", "uint8", "bool"}


class ArdyError(RuntimeError):
    """The server reported a failure for a command."""


class ArdyTimeout(TimeoutError):
    """No response arrived within the timeout."""


# --------------------------------------------------------------------------
# tensor codec
# --------------------------------------------------------------------------


def encode_tensor(array) -> dict[str, Any]:
    """Encode an ndarray as ``{"b64": ..., "shape": [...], "dtype": ...}``.

    float64 is narrowed to float32 on the wire: motion data does not need the
    precision and it halves every payload.
    """
    array = np.ascontiguousarray(array)
    if array.dtype == np.float64:
        array = array.astype(np.float32)
    name = np.dtype(array.dtype).name
    if name not in _ALLOWED_DTYPES:
        raise ValueError(f"dtype {name!r} is not supported on the wire; cast it first")
    return {
        "b64": base64.b64encode(array.tobytes()).decode("ascii"),
        "shape": list(array.shape),
        "dtype": name,
    }


def decode_tensor(obj) -> np.ndarray | None:
    """Inverse of :func:`encode_tensor`. Passes ``None`` through unchanged."""
    if obj is None:
        return None
    if isinstance(obj, np.ndarray):
        return obj
    name = obj.get("dtype", "float32")
    if name not in _ALLOWED_DTYPES:
        raise ValueError(f"dtype {name!r} is not supported on the wire")
    raw = base64.b64decode(obj["b64"])
    return np.frombuffer(raw, dtype=np.dtype(name)).reshape(tuple(obj["shape"]))


def _encode_maybe(value):
    """Encode ndarrays, leave everything else (including None) alone."""
    return encode_tensor(value) if isinstance(value, np.ndarray) else value


def _decode_required(msg: dict, key: str, cmd: str) -> np.ndarray:
    """Decode a tensor field that the reply is required to carry.

    A reply missing its payload is a protocol error, not an empty result, so
    surface it here rather than handing back None for the caller to trip over.
    """
    array = decode_tensor(msg.get(key))
    if array is None:
        raise ArdyError(f"{cmd}: reply carried no {key!r} field")
    return array


def _encode_mapping(mapping: dict | None) -> dict | None:
    """Encode every ndarray value in a flat mapping, e.g. the mask bundle."""
    if mapping is None:
        return None
    return {key: _encode_maybe(value) for key, value in mapping.items()}


# --------------------------------------------------------------------------
# client-owned state
# --------------------------------------------------------------------------


@dataclass
class ModelInfo:
    """Dimensions of the model the server has loaded.

    A client that owns session state needs these to size its own tensors.
    """

    model_name: str = ""
    skeleton: str = ""
    fps: float = 0.0
    gen_horizon_len: int = 0
    num_frames_per_token: int = 0
    nframe_root_dim: int = 0
    latent_embedding_dim: int = 0
    motion_rep_dim: int = 0
    num_base_steps: int = 0
    encode_with_quantization: bool = False

    @property
    def token_dim(self) -> int:
        """Width of one hybrid token: explicit root channels plus latent body."""
        return self.nframe_root_dim + self.latent_embedding_dim

    @property
    def num_generation_tokens(self) -> int:
        """Tokens written per autoregressive step."""
        if self.num_frames_per_token == 0:
            return 0
        return self.gen_horizon_len // self.num_frames_per_token

    @property
    def horizon_seconds(self) -> float:
        """Wall-clock duration of one generated block."""
        return self.gen_horizon_len / self.fps if self.fps else 0.0

    @classmethod
    def from_event(cls, msg: dict) -> "ModelInfo":
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in msg.items() if k in fields})


@dataclass
class ArdySession:
    """One character's generation state. Owned by the client, never the server.

    ``history`` holds hybrid tokens, ``[B, N, token_dim]``. ``global_transl``
    and ``first_heading_angle`` carry the world-space frame that the recentered
    local history is expressed against.
    """

    session_id: str = "default"
    batch_size: int = 1
    history: np.ndarray | None = None
    global_transl: np.ndarray | None = None
    first_heading_angle: np.ndarray | None = None
    frames_emitted: int = 0
    text_feat: np.ndarray | None = None
    text_pad_mask: np.ndarray | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def num_tokens(self) -> int:
        return 0 if self.history is None else int(self.history.shape[1])

    def reset(self) -> None:
        """Drop all generated motion, keeping the prompt conditioning."""
        self.history = None
        self.global_transl = None
        self.first_heading_angle = None
        self.frames_emitted = 0

    def append_tokens(self, tokens: np.ndarray, frames_per_token: int) -> None:
        """Append newly generated tokens to the history."""
        tokens = np.asarray(tokens)
        if self.history is None:
            self.history = tokens
        else:
            self.history = np.concatenate([self.history, tokens], axis=1)
        self.frames_emitted += int(tokens.shape[1]) * int(frames_per_token)

    def history_window(self, max_tokens: int | None) -> np.ndarray | None:
        """The most recent ``max_tokens`` tokens, the model's history context.

        Mirrors the demo's History Crop Length: a short window adapts to a new
        prompt quickly, a long one gives smoother, more coherent motion.
        """
        if self.history is None or max_tokens is None:
            return self.history
        if max_tokens <= 0:
            return None
        return self.history[:, -max_tokens:]


# --------------------------------------------------------------------------
# client
# --------------------------------------------------------------------------


class _Pending:
    __slots__ = ("done", "msg")

    def __init__(self):
        self.done = threading.Event()
        self.msg: dict | None = None


class ArdyClient(ToolClient):
    """Blocking client for the ``ardy`` interface.

    Every command is request/response, correlated by ``req_id``, so the
    denoising loop reads as straight-line code::

        with ArdyClient() as client:
            info = client.model_info()
            session = client.new_session()
            x = rng.standard_normal((1, info.num_generation_tokens, info.token_dim))
            for t in reversed(range(steps)):
                x = client.denoise(x, t, steps, text_feat, text_pad_mask, masks, heading)
            motion = client.detokenize(x)

    Event handlers registered with :meth:`on` still work for anything the
    server broadcasts without a ``req_id``.
    """

    def __init__(self, name: str = "ardy", timeout: float = DEFAULT_TIMEOUT):
        super().__init__(name)
        self.timeout = timeout
        self.sessions: dict[str, ArdySession] = {}
        self._info: ModelInfo | None = None
        self._pending: dict[int, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._req_ids = itertools.count(1)

    # --- session ownership -------------------------------------------------

    def new_session(self, session_id: str = "default", batch_size: int = 1) -> ArdySession:
        """Create (or replace) a session. State lives here, not on the server."""
        session = ArdySession(session_id=session_id, batch_size=batch_size)
        self.sessions[session_id] = session
        return session

    def session(self, session_id: str = "default") -> ArdySession:
        """Fetch a session, creating it on first use."""
        if session_id not in self.sessions:
            return self.new_session(session_id)
        return self.sessions[session_id]

    # --- request plumbing --------------------------------------------------

    def msg_handler_fn(self, msg: dict, pid: int | None = None):
        """Route correlated replies to their waiter; delegate the rest."""
        req_id = msg.get("req_id")
        if req_id is not None:
            with self._pending_lock:
                slot = self._pending.pop(req_id, None)
            if slot is not None:
                slot.msg = msg
                slot.done.set()
                return
        super().msg_handler_fn(msg, pid)

    def _request(self, cmd: str, timeout: float | None = None, **kwargs) -> dict:
        """Send *cmd* and block until its reply (or an error) comes back."""
        req_id = next(self._req_ids)
        slot = _Pending()
        with self._pending_lock:
            self._pending[req_id] = slot

        payload = {k: v for k, v in kwargs.items() if v is not None}
        try:
            self.send_command(cmd, req_id=req_id, **payload)
        except Exception:
            with self._pending_lock:
                self._pending.pop(req_id, None)
            raise

        if not slot.done.wait(self.timeout if timeout is None else timeout):
            with self._pending_lock:
                self._pending.pop(req_id, None)
            raise ArdyTimeout(f"no response to {cmd!r} (req_id={req_id}) within {timeout or self.timeout}s")

        msg = slot.msg or {}
        if msg.get("event") == "error":
            raise ArdyError(f"{cmd}: {msg.get('message', 'server reported an error')}")
        return msg

    # --- commands ----------------------------------------------------------

    def model_info(self, refresh: bool = False) -> ModelInfo:
        """Dimensions of the loaded model. Cached after the first call."""
        if self._info is None or refresh:
            self._info = ModelInfo.from_event(self._request("model_info"))
        return self._info

    def tokenize(self, motion: np.ndarray, timeout: float | None = None) -> np.ndarray:
        """Explicit motion frames ``[B, T, D]`` -> hybrid tokens.

        Use this to seed a session from motion the client already has, e.g. a
        captured clip or the pose the character is currently holding.
        """
        msg = self._request("tokenize", timeout=timeout, motion=encode_tensor(motion))
        return _decode_required(msg, "tokens", "tokenize")

    def detokenize(self, tokens: np.ndarray, timeout: float | None = None) -> np.ndarray:
        """Hybrid tokens -> explicit motion frames ``[B, T, D]``."""
        msg = self._request("detokenize", timeout=timeout, tokens=encode_tensor(tokens))
        return _decode_required(msg, "motion", "detokenize")

    def requantize(self, latent: np.ndarray, timeout: float | None = None) -> np.ndarray:
        """Re-quantize latent body channels after the client recenters history.

        Only meaningful when ``model_info().encode_with_quantization`` is true;
        it is a no-op round trip otherwise.
        """
        msg = self._request("requantize", timeout=timeout, latent=encode_tensor(latent))
        return _decode_required(msg, "latent", "requantize")

    def denoise(
        self,
        x: np.ndarray,
        t: int,
        num_denoising_steps: int,
        text_feat: np.ndarray,
        text_pad_mask: np.ndarray,
        masks: dict[str, Any],
        first_heading_angle: np.ndarray,
        motion_mask: np.ndarray | None = None,
        observed_motion: np.ndarray | None = None,
        cfg_weight: float | Iterable[float] | None = None,
        cfg_type: str | None = None,
        timeout: float | None = None,
    ) -> np.ndarray:
        """One denoising step. Returns ``x`` after the sampler, i.e. x_{t-1}.

        Only tokens selected by ``masks["generation_token_mask"]`` are written;
        history tokens pass through untouched, which is what makes consecutive
        blocks join without a seam. Call once per timestep, descending.
        """
        # A scalar guides text and constraints together; a pair guides them
        # separately (text weight, constraint weight).
        wire_cfg: float | list[float] | None
        if cfg_weight is None:
            wire_cfg = None
        elif isinstance(cfg_weight, (int, float)):
            wire_cfg = float(cfg_weight)
        else:
            wire_cfg = [float(w) for w in cfg_weight]

        msg = self._request(
            "denoise",
            timeout=timeout,
            x=encode_tensor(x),
            t=int(t),
            num_denoising_steps=int(num_denoising_steps),
            text_feat=encode_tensor(text_feat),
            text_pad_mask=encode_tensor(text_pad_mask),
            masks=_encode_mapping(masks),
            first_heading_angle=encode_tensor(first_heading_angle),
            motion_mask=_encode_maybe(motion_mask),
            observed_motion=_encode_maybe(observed_motion),
            cfg_weight=wire_cfg,
            cfg_type=cfg_type,
        )
        return _decode_required(msg, "x", "denoise")

    def denoise_loop(
        self,
        x: np.ndarray,
        num_denoising_steps: int,
        *,
        progress=None,
        **kwargs,
    ) -> np.ndarray:
        """Run the full descending schedule, one round trip per step.

        ``progress`` is an optional ``callable(step_index, total)`` for UI.
        Everything else is forwarded to :meth:`denoise`.
        """
        for i, t in enumerate(reversed(range(num_denoising_steps))):
            x = self.denoise(x, t, num_denoising_steps, **kwargs)
            if progress is not None:
                progress(i + 1, num_denoising_steps)
        return x

    # --- teardown ----------------------------------------------------------

    def _fail_pending(self, reason: str) -> None:
        """Wake every waiter so a closing client can't leave a thread blocked."""
        with self._pending_lock:
            pending, self._pending = self._pending, {}
        for slot in pending.values():
            slot.msg = {"event": "error", "message": reason}
            slot.done.set()

    def __exit__(self, *exc):
        self._fail_pending("client closed")
        return super().__exit__(*exc)
