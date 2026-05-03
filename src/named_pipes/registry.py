"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

Model registry — catalogue of known models, the server type(s) they work
with, and the backend(s) each is compatible with.
"""

from dataclasses import dataclass, field
from enum import Enum


class ServerType(str, Enum):
    CHAT = "chat"
    TTS = "tts"
    STT = "stt"


class Backend(str, Enum):
    # chat backends
    TRANSFORMERS = "transformers"
    VLLM = "vllm"
    VLLM_OMNI = "vllm_omni"
    # TTS backends
    MLX_AUDIO = "mlx_audio"
    # STT backends
    VOXTRAL = "voxtral"


@dataclass
class ModelEntry:
    hub_id: str
    servers: list[ServerType]
    backends: list[Backend]
    default: bool = False
    description: str = ""


REGISTRY: list[ModelEntry] = [
    ModelEntry(
        hub_id="Qwen/Qwen3.5-0.8B",
        servers=[ServerType.CHAT],
        backends=[Backend.TRANSFORMERS, Backend.VLLM],
        default=True,
        description="Qwen 3.5 0.8B — default chat model",
    ),
    ModelEntry(
        hub_id="mlx-community/Kokoro-82M-bf16",
        servers=[ServerType.TTS],
        backends=[Backend.MLX_AUDIO],
        default=True,
        description="Kokoro 82M (bfloat16) — default TTS model",
    ),
    ModelEntry(
        hub_id="mlx-community/Voxtral-Mini-4B-Realtime-6bit",
        servers=[ServerType.STT],
        backends=[Backend.VOXTRAL],
        default=True,
        description="Voxtral Mini 4B Realtime (6-bit) — default STT model",
    ),
]


def models_for(server: ServerType) -> list[ModelEntry]:
    """Return all registry entries compatible with *server*."""
    return [m for m in REGISTRY if server in m.servers]


def default_for(server: ServerType) -> ModelEntry | None:
    """Return the default model for *server*, or None if not set."""
    return next((m for m in REGISTRY if server in m.servers and m.default), None)
