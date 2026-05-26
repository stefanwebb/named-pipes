"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

Model registry — catalogue of known models, the server type(s) they work
with, and the backend(s) each is compatible with.
"""

# TODO: Make the registry load from a toml or json file
# TODO: Make chat.server.Backend enum derive from registry

from dataclasses import dataclass, field
from enum import Enum

from named_pipes.interfaces import BASE, CHAT, TTS, STT, Interface


class ServerType(str, Enum):
    CHAT = "chat"
    TTS = "tts"
    STT = "stt"


class Backend(str, Enum):
    # chat backends
    TRANSFORMERS = "transformers"
    VLLM = "vllm"
    VLLM_MLX = "vlm_mlx"
    MLX_LM = "mlx_lm"
    # TTS backends
    MLX_AUDIO = "mlx_audio"
    # STT backends
    VOXTRAL = "voxtral"


@dataclass
class BackendEntry:
    name: str                  # Python library name / import name
    servers: list[ServerType]
    platforms: list[str]       # platform.system() values: "Darwin", "Linux"


BACKENDS: dict[Backend, BackendEntry] = {
    Backend.TRANSFORMERS: BackendEntry(
        name="transformers",
        servers=[ServerType.CHAT],
        platforms=["Darwin", "Linux"],
    ),
    Backend.VLLM: BackendEntry(
        name="vllm",
        servers=[ServerType.CHAT],
        platforms=["Linux"],
    ),
    Backend.VLLM_MLX: BackendEntry(
        name="vllm_mlx",
        servers=[ServerType.CHAT],
        platforms=["Darwin"],
    ),
    Backend.MLX_LM: BackendEntry(
        name="mlx_lm",
        servers=[ServerType.CHAT],
        platforms=["Darwin"],
    ),
    Backend.MLX_AUDIO: BackendEntry(
        name="mlx_audio",
        servers=[ServerType.TTS],
        platforms=["Darwin"],
    ),
    Backend.VOXTRAL: BackendEntry(
        name="voxtral",
        servers=[ServerType.STT],
        platforms=["Darwin"],
    ),
}


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
        description="Qwen3.5 0.8B — default chat model",
    ),
    ModelEntry(
        hub_id="Qwen/Qwen3-0.6B",
        servers=[ServerType.CHAT],
        backends=[Backend.TRANSFORMERS, Backend.VLLM],
        default=True,
        description="Qwen3 0.6B",
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


INTERFACES: dict[str, Interface] = {
    iface.name: iface for iface in [BASE, CHAT, TTS, STT]
}


def models_for(server: ServerType) -> list[ModelEntry]:
    """Return all registry entries compatible with *server*."""
    return [m for m in REGISTRY if server in m.servers]


def default_for(server: ServerType) -> ModelEntry | None:
    """Return the default model for *server*, or None if not set."""
    return next((m for m in REGISTRY if server in m.servers and m.default), None)


def models_for_backend(server: ServerType, backend: Backend) -> list[ModelEntry]:
    """Return all registry entries compatible with *server* and *backend*."""
    return [m for m in REGISTRY if server in m.servers and backend in m.backends]


def default_for_backend(server: ServerType, backend: Backend) -> ModelEntry | None:
    """Return the default model for *server*/*backend*, falling back to first match."""
    entries = models_for_backend(server, backend)
    return next((m for m in entries if m.default), entries[0] if entries else None)
