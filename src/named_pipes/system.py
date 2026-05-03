"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

import importlib.metadata
import platform
from dataclasses import dataclass, field

from named_pipes.utils import get_version


def _optional_version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _cpu_info() -> str:
    if platform.system() == "Darwin":
        import subprocess

        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            name = result.stdout.strip()
            if name:
                return name
        except Exception:
            pass
    return platform.processor() or platform.machine()


def _gpu_info() -> list[str]:
    # CUDA GPUs via PyTorch
    try:
        import torch

        if torch.cuda.is_available():
            return [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    except ImportError:
        pass

    # Apple Silicon MPS
    try:
        import torch

        if torch.backends.mps.is_available():
            return ["Apple Silicon (MPS)"]
    except ImportError:
        pass

    return []


def _ram_gb() -> float | None:
    try:
        import psutil

        return round(psutil.virtual_memory().total / (1024**3), 1)
    except ImportError:
        return None


def _cuda_version() -> str | None:
    try:
        import torch

        if torch.cuda.is_available():
            return torch.version.cuda
    except ImportError:
        pass
    return None


@dataclass
class SystemInfo:
    platform: str
    cpu: str
    gpus: list[str]
    ram_gb: float | None

    named_pipes_version: str
    torch_version: str | None
    transformers_version: str | None
    vllm_version: str | None
    cuda_version: str | None
    mlx_lm_version: str | None
    vllm_mlx_version: str | None
    mlx_audio_version: str | None

    extra: dict = field(default_factory=dict)

    def __str__(self) -> str:
        lines = [
            f"Platform:        {self.platform}",
            f"CPU:             {self.cpu}",
            f"RAM:             {self.ram_gb} GB" if self.ram_gb is not None else "RAM:             unknown",
            f"GPUs:            {', '.join(self.gpus) if self.gpus else 'none detected'}",
            f"Named Pipes:     {self.named_pipes_version}",
            f"PyTorch:         {self.torch_version or 'not installed'}",
            f"Transformers:    {self.transformers_version or 'not installed'}",
            f"vLLM:            {self.vllm_version or 'not installed'}",
            f"CUDA:            {self.cuda_version or 'not available'}",
            f"mlx-lm:          {self.mlx_lm_version or 'not installed'}",
            f"vllm-mlx:        {self.vllm_mlx_version or 'not installed'}",
            f"mlx-audio:       {self.mlx_audio_version or 'not installed'}",
        ]
        return "\n".join(lines)


def get_system_info() -> SystemInfo:
    return SystemInfo(
        platform=platform.platform(),
        cpu=_cpu_info(),
        gpus=_gpu_info(),
        ram_gb=_ram_gb(),
        named_pipes_version=get_version(),
        torch_version=_optional_version("torch"),
        transformers_version=_optional_version("transformers"),
        vllm_version=_optional_version("vllm"),
        cuda_version=_cuda_version(),
        mlx_lm_version=_optional_version("mlx-lm"),
        vllm_mlx_version=_optional_version("vllm-mlx"),
        mlx_audio_version=_optional_version("mlx-audio"),
    )
