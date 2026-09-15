"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

ArdyServer — serves ARDY motion-diffusion inference over a named pipe.

The server is a **stateless evaluator**. It holds the weights and answers four
commands; it remembers nothing between calls. All session state — history
tokens, accumulated world translation, first-frame heading, and the denoising
loop itself — belongs to the client (see ``named_pipes.ardy.client``).

It deliberately does **not** load a text encoder. ``denoise`` takes ``text_feat``
as an argument, so prompt embedding happens elsewhere. That keeps this process
at roughly the size of the motion model (~0.8 GB) instead of the ~17 GB it would
take with LLM2Vec/Llama-3-8B resident.

Model loading is inlined here (see ``load_model``) rather than imported from
``ardy.model.load_model``, so this module imports neither ``ardy`` nor Hydra /
OmegaConf. The checkpoint's ``config.yaml`` is a Hydra-style tree of ``_target_``
class paths, which ``_instantiate`` below imports and calls directly -- so the
``ardy`` package (https://github.com/nv-tlabs/ardy) must still be importable at
load time; it is not on PyPI, so install it separately.

Usage:
    python -m named_pipes.ardy.launch
    python -m named_pipes.ardy.launch '{"model": "nvidia/ARDY-Core-RP-20FPS-Horizon8", "device": "mps"}'
"""

import importlib
import os
import re
import threading
import traceback
from enum import Enum
from pathlib import Path

import numpy as np
import torch
from pydantic import BaseModel

from named_pipes.ardy.client import decode_tensor, encode_tensor
from named_pipes.tools.server import ToolServer, ToolState

DEFAULT_MODEL = "nvidia/ARDY-Core-RP-20FPS-Horizon40"

__all__ = ["DEFAULT_MODEL", "ArdyConfig", "ArdyServer", "ArdyState", "load_model", "select_device"]


class ArdyState(Enum):
    RUNNING = ToolState.RUNNING.value
    STOPPING = ToolState.STOPPING.value
    LOADING = "loading"
    IDLE = "idle"
    EVALUATING = "evaluating"
    ERROR = "error"


class ArdyConfig(BaseModel):
    """Everything needed to stand a server up."""

    name: str = "ardy"
    model: str = DEFAULT_MODEL  # HF repo id, or a local checkpoint folder
    device: str | None = None  # None -> auto: cuda, then mps, then cpu


def select_device(requested: str | None = None) -> str:
    """Resolve a device, honouring ARDY_DEVICE, then cuda -> mps -> cpu."""
    requested = requested or os.environ.get("ARDY_DEVICE")
    if requested:
        return requested
    if torch.cuda.is_available():
        return "cuda:0"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


# ---------------------------------------------------------------------------
# model loading (inlined from ardy.model.load_model)
# ---------------------------------------------------------------------------

# ``${key}`` / ``${oc.select:key}`` / ``${oc.select:key,default}`` -- the only
# OmegaConf interpolation forms the released configs use.
_INTERP = re.compile(r"\$\{(?:oc\.select:)?([A-Za-z_][\w.]*)(?:,([^}]*))?\}")


def _resolve(node, root: dict):
    """Substitute ``${...}`` interpolations, looking keys up in ``root``.

    ``${oc.select:checkpoint_dir}`` in the released configs points every
    ``ckpt_path`` / ``stats_path`` at the snapshot folder; a missing key
    resolves to its default (or ``None``, like ``oc.select``).
    """
    if isinstance(node, dict):
        return {k: _resolve(v, root) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve(v, root) for v in node]
    if not isinstance(node, str) or "${" not in node:
        return node

    def lookup(match: re.Match):
        value = root
        for part in match.group(1).split("."):
            value = value.get(part) if isinstance(value, dict) else None
            if value is None:
                break
        if value is None:
            value = match.group(2)
        return "" if value is None else str(value)

    return _INTERP.sub(lookup, node)


def _instantiate(node, **overrides):
    """Hydra-style ``instantiate``: build the object named by ``_target_``.

    Children are instantiated first, then the class is imported and called with
    the remaining keys (plus ``overrides``) as kwargs. Dicts without a
    ``_target_`` are passed through as plain dicts.
    """
    if isinstance(node, list):
        return [_instantiate(v) for v in node]
    if not isinstance(node, dict):
        return node
    kwargs = {k: _instantiate(v) for k, v in node.items() if k != "_target_"}
    target = node.get("_target_")
    if target is None:
        return kwargs
    module_name, _, class_name = target.rpartition(".")
    cls = getattr(importlib.import_module(module_name), class_name)
    return cls(**kwargs, **overrides)


def load_model(model: str = DEFAULT_MODEL, device: str = "cpu"):
    """Load a released ARDY model *without* a text encoder.

    A trimmed-down copy of ``ardy.model.load_model.load_model(text_encoder=False,
    return_config=True)`` that reads ``config.yaml`` with PyYAML and builds the
    module tree itself instead of going through Hydra. ``model`` is either a
    Hugging Face repo id (default :data:`DEFAULT_MODEL`, fetched with
    ``snapshot_download`` and cached) or the path of a local checkpoint folder
    holding ``config.yaml``, the ``*.safetensors`` files and ``stats/``.

    Returns ``(model, model_cfg)`` with the model in eval mode.
    """
    import yaml

    model_path = Path(model)
    if not model_path.is_dir():
        from huggingface_hub import snapshot_download

        model_path = Path(snapshot_download(repo_id=model))

    model_config_path = model_path / "config.yaml"
    if not model_config_path.exists():
        raise FileNotFoundError(
            f"The model folder exists but config.yaml is missing: {model_config_path}"
        )

    with open(model_config_path) as fh:
        model_conf = yaml.safe_load(fh)
    model_cfg = _resolve(model_conf, {**model_conf, "checkpoint_dir": str(model_path)})
    # Never build the (16 GB) text encoder; Ardy accepts text_encoder=None.
    model_cfg["text_encoder"] = None

    # Imports and constructs the ``ardy.model.*`` classes named by ``_target_``.
    model = _instantiate(model_cfg, device=device)
    return model.eval(), model_cfg


# ---------------------------------------------------------------------------
# tensor plumbing
# ---------------------------------------------------------------------------


def _to_torch(obj, device, *, dtype=None) -> torch.Tensor | None:
    """Wire tensor -> torch, on ``device``. Passes None through."""
    array = decode_tensor(obj)
    if array is None:
        return None
    # np.frombuffer gives a read-only view; copy so torch owns writable memory.
    tensor = torch.from_numpy(np.array(array, copy=True)).to(device)
    if dtype is not None:
        tensor = tensor.to(dtype)
    elif tensor.is_floating_point():
        tensor = tensor.to(torch.float32)
    return tensor


def _from_torch(tensor: torch.Tensor) -> dict:
    """torch -> wire tensor, always via CPU."""
    return encode_tensor(tensor.detach().cpu().numpy())


def _as_lengths(value, batch_size: int, device) -> torch.Tensor:
    """Accept an int or a per-batch array; return a ``[B]`` long tensor.

    ``denoising_step`` wants lengths as tensors, but it is far friendlier for a
    client to send a plain integer.
    """
    if isinstance(value, (int, float)):
        return torch.full((batch_size,), int(value), dtype=torch.long, device=device)
    tensor = _to_torch(value, device, dtype=torch.long)
    if tensor is None:
        raise ValueError("missing length field")
    return tensor.reshape(-1)


# ---------------------------------------------------------------------------
# server
# ---------------------------------------------------------------------------


class ArdyServer(ToolServer):
    """Named-pipe server exposing the ``ardy`` interface."""

    def __init__(self, config: ArdyConfig):
        super().__init__(
            config.name,
            description=f"ARDY motion diffusion inference ({config.model})",
        )
        self.config = config
        self.device = select_device(config.device)

        # One command at a time. MPS is not thread-safe, and even on CUDA
        # overlapping forward passes on one model buys nothing here.
        self._eval_lock = threading.RLock()

        self.set_state(ArdyState.LOADING)
        print(f"[ardy] loading '{config.model}' on {self.device} (no text encoder)...", flush=True)
        # load_model never attaches a text encoder: denoise() is handed
        # text_feat by the caller, so this process never loads the 16 GB LLM.
        self.model, self.model_cfg = load_model(config.model, device=self.device)
        self._info = self._build_info()
        print(f"[ardy] ready: {self._info['model_name']} @ {self._info['fps']} fps", flush=True)

        self._register_ardy_handlers()
        self.set_state(ArdyState.IDLE)

    # --- introspection -----------------------------------------------------

    def _list_interfaces(self) -> list[str]:
        return ["base", "ardy"]

    def _get_config(self) -> dict:
        return self.config.model_dump()

    def _build_info(self) -> dict:
        """Dimensions a stateful client needs to size its own tensors."""
        model = self.model
        skeleton = getattr(model.motion_rep.skeleton, "name", "")
        return {
            "model_name": self.model_cfg.get("model_name", self.config.model),
            "skeleton": skeleton,
            "fps": float(model.motion_rep.fps),
            "gen_horizon_len": int(model.gen_horizon_len),
            "num_frames_per_token": int(model.num_frames_per_token),
            "nframe_root_dim": int(model.denoiser.nframe_root_dim),
            "latent_embedding_dim": int(model.denoiser.latent_embedding_dim),
            "motion_rep_dim": int(model.motion_rep.motion_rep_dim),
            "num_base_steps": int(model.diffusion.num_base_steps),
            "encode_with_quantization": bool(
                getattr(model.autoencoder, "encode_with_quantization", False)
            ),
        }

    # --- handler plumbing --------------------------------------------------

    def _command(self, cmd: str, event: str):
        """Register a handler that replies with *event*, echoing ``req_id``.

        The wrapped function takes the message and returns the event's fields.
        Any exception is reported to the caller as an ``error`` event rather
        than killing the listener thread.
        """

        def decorator(fn):
            @self.handler(cmd)
            def _wrapped(msg, pid):
                req_id = msg.get("req_id")
                try:
                    with self._eval_lock:
                        self.set_state(ArdyState.EVALUATING)
                        try:
                            fields = fn(msg)
                        finally:
                            self.set_state(ArdyState.IDLE)
                except Exception as exc:  # noqa: BLE001 - reported to the client
                    traceback.print_exc()
                    self.send_event(
                        "error",
                        pid,
                        req_id=req_id,
                        cmd=cmd,
                        message=f"{type(exc).__name__}: {exc}",
                    )
                    return
                self.send_event(event, pid, req_id=req_id, **fields)

            return fn

        return decorator

    def _register_ardy_handlers(self):
        device = self.device
        model = self.model
        frames_per_token = int(model.num_frames_per_token)

        @self._command("model_info", "model_info")
        def _model_info(msg):
            return dict(self._info)

        @self._command("tokenize", "tokenized")
        def _tokenize(msg):
            motion = _to_torch(msg.get("motion"), device)
            if motion is None or motion.ndim != 3:
                raise ValueError("tokenize needs a [B, T, D] 'motion' tensor")
            batch, frames, _ = motion.shape
            if frames % frames_per_token:
                raise ValueError(
                    f"frame count {frames} is not a multiple of num_frames_per_token "
                    f"({frames_per_token})"
                )
            pad_mask = torch.ones(batch, frames, dtype=torch.bool, device=device)
            lengths = torch.full((batch,), frames, dtype=torch.long, device=device)
            with torch.inference_mode():
                tokens, _ = model.hybrid.get_hybrid_motion_from_explicit(
                    motion=motion, motion_len=lengths, motion_pad_mask=pad_mask
                )
            return {"tokens": _from_torch(tokens)}

        @self._command("detokenize", "detokenized")
        def _detokenize(msg):
            tokens = _to_torch(msg.get("tokens"), device)
            if tokens is None or tokens.ndim != 3:
                raise ValueError("detokenize needs a [B, N, D] 'tokens' tensor")
            batch, num_tokens, _ = tokens.shape
            frames = num_tokens * frames_per_token
            pad_mask = torch.ones(batch, frames, dtype=torch.bool, device=device)
            lengths = torch.full((batch,), frames, dtype=torch.long, device=device)
            with torch.inference_mode():
                motion = model.hybrid.get_explicit_motion_from_hybrid(
                    hybrid_motion=tokens, motion_pad_mask=pad_mask, motion_len=lengths
                )
            return {"motion": _from_torch(motion)}

        @self._command("requantize", "requantized")
        def _requantize(msg):
            if not self._info["encode_with_quantization"]:
                raise ValueError("this autoencoder does not quantize; requantize is not available")
            latent = _to_torch(msg.get("latent"), device)
            if latent is None:
                raise ValueError("requantize needs a 'latent' tensor")
            with torch.inference_mode():
                out = model.autoencoder.requantize(latent)
            return {"latent": _from_torch(out)}

        @self._command("denoise", "denoised")
        def _denoise(msg):
            x = _to_torch(msg.get("x"), device)
            if x is None or x.ndim != 3:
                raise ValueError("denoise needs a [B, N, D] 'x' tensor")
            batch = x.shape[0]

            masks = msg.get("masks") or {}
            required = (
                "history_mask",
                "generation_mask",
                "future_mask",
                "history_token_mask",
                "generation_token_mask",
                "future_token_mask",
            )
            missing = [k for k in required if k not in masks]
            if missing:
                raise ValueError(f"denoise 'masks' is missing: {', '.join(missing)}")

            mask_tensors = {k: _to_torch(masks[k], device, dtype=torch.bool) for k in required}

            base_steps = self._info["num_base_steps"]
            steps = int(msg.get("num_denoising_steps", base_steps))
            t_index = int(msg.get("t", 0))
            # space_timesteps() always returns a map_tensor of num_base_steps
            # entries and denoising_step indexes it with t, so num_base_steps --
            # not num_denoising_steps -- is the real bound. Asking for more
            # steps than the model was trained with indexes off the end.
            if steps < 1 or steps > base_steps:
                raise ValueError(
                    f"num_denoising_steps={steps} must be in [1, {base_steps}] "
                    f"for this model (num_base_steps={base_steps})"
                )
            if not 0 <= t_index < base_steps:
                raise ValueError(f"t={t_index} is outside the schedule [0, {base_steps})")

            cfg_weight = msg.get("cfg_weight", 2.0)
            if isinstance(cfg_weight, list):
                cfg_weight = tuple(float(w) for w in cfg_weight)

            with torch.inference_mode():
                out = model.denoising_step(
                    x,
                    _as_lengths(masks.get("history_len", 0), batch, device),
                    _as_lengths(masks.get("generation_len", model.gen_horizon_len), batch, device),
                    _as_lengths(masks.get("future_len", 0), batch, device),
                    mask_tensors["history_mask"],
                    mask_tensors["generation_mask"],
                    mask_tensors["future_mask"],
                    mask_tensors["history_token_mask"],
                    mask_tensors["generation_token_mask"],
                    mask_tensors["future_token_mask"],
                    _to_torch(msg.get("text_feat"), device),
                    _to_torch(msg.get("text_pad_mask"), device, dtype=torch.bool),
                    torch.full((batch,), t_index, dtype=torch.long, device=device),
                    _to_torch(msg.get("first_heading_angle"), device),
                    _to_torch(msg.get("motion_mask"), device),
                    _to_torch(msg.get("observed_motion"), device),
                    torch.tensor([steps], dtype=torch.long, device=device),
                    cfg_weight,
                    cfg_type=msg.get("cfg_type"),
                )
            return {"x": _from_torch(out), "t": t_index}
