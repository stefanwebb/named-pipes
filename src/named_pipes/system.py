"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

import importlib.metadata
import os
import platform
import threading
from dataclasses import dataclass, field

from named_pipes.utils import get_version, scan_pipes


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
    # Hardware
    platform: str
    cpu: str
    gpus: list[str]
    ram_gb: float | None
    cuda_version: str | None

    # Libraries
    named_pipes_version: str
    torch_version: str | None
    transformers_version: str | None
    vllm_version: str | None
    vllm_omni_version: str | None
    mlx_lm_version: str | None
    vllm_mlx_version: str | None
    mlx_audio_version: str | None

    extra: dict = field(default_factory=dict)

    def hardware_str(self) -> str:
        is_mac = self.platform.startswith("macOS") or "Darwin" in self.platform
        lines = [
            f"  Platform:      {self.platform}",
            f"  CPU:           {self.cpu}",
            f"  RAM:           {self.ram_gb} GB" if self.ram_gb is not None else "  RAM:           unknown",
            f"  GPUs:          {', '.join(self.gpus) if self.gpus else 'none detected'}",
        ]
        if not is_mac:
            lines.append(f"  CUDA:          {self.cuda_version or 'not available'}")
        return "\n".join(lines)

    def libraries_str(self) -> str:
        is_mac = self.platform.startswith("macOS") or "Darwin" in self.platform
        entries: list[tuple[str, str | None, bool]] = [
            # (label, version, always_show)
            ("named_pipes", self.named_pipes_version, True),
            ("torch", self.torch_version, True),
            ("transformers", self.transformers_version, True),
            ("vllm", self.vllm_version, not is_mac),
            ("vllm_omni", self.vllm_omni_version, not is_mac),
            ("mlx_lm", self.mlx_lm_version, is_mac),
            ("mlx_audio", self.mlx_audio_version, is_mac),
            ("vllm_mlx", self.vllm_mlx_version, is_mac),
        ]
        lines = [
            f"  {name:<14} {ver if ver is not None else 'not installed'}"
            for name, ver, show in entries
            if show
        ]
        return "\n".join(lines)

    def __str__(self) -> str:
        return f"Hardware\n{self.hardware_str()}\n\nLibraries\n{self.libraries_str()}"


@dataclass
class ToolInfo:
    name: str
    running: bool
    description: str | None = None


def _tool_name_from_path(path: str) -> str | None:
    """Extract tool name from /tmp/tool-{name}, ignoring per-pid pipes."""
    basename = os.path.basename(path)
    if not basename.startswith("tool-"):
        return None
    suffix = basename[len("tool-"):]
    # per-pid downstream pipes end with -<digits>
    parts = suffix.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return None
    return suffix


def _fetch_description(name: str, timeout: float = 2.0) -> str | None:
    from named_pipes.tools.client import ToolClient

    got = threading.Event()
    result: list[str | None] = [None]

    try:
        client = ToolClient(name)

        @client.on("description")
        def _(msg):
            result[0] = msg.get("description")
            got.set()

        client.listen()
        client.subscribe()
        client.send_command("get_description")
        got.wait(timeout=timeout)
        client.unsubscribe()
        client._close()
    except Exception:
        pass

    return result[0]


def get_tools_info() -> list[ToolInfo]:
    pipe_data = scan_pipes("/tmp", with_pids=False)
    tools: list[ToolInfo] = []

    for entry in pipe_data["connected"]:
        name = _tool_name_from_path(entry["path"])
        if name is None:
            continue
        description = _fetch_description(name)
        tools.append(ToolInfo(name=name, running=True, description=description))

    for path in pipe_data["orphaned"]:
        name = _tool_name_from_path(path)
        if name is None:
            continue
        tools.append(ToolInfo(name=name, running=False))

    return sorted(tools, key=lambda t: (not t.running, t.name))


def get_system_info() -> SystemInfo:
    return SystemInfo(
        platform=platform.platform(),
        cpu=_cpu_info(),
        gpus=_gpu_info(),
        ram_gb=_ram_gb(),
        # Replace with a dictionary from library name to version
        cuda_version=_cuda_version(),
        named_pipes_version=get_version(),
        torch_version=_optional_version("torch"),
        transformers_version=_optional_version("transformers"),
        vllm_version=_optional_version("vllm"),
        vllm_omni_version=_optional_version("vllm-omni"),
        mlx_lm_version=_optional_version("mlx-lm"),
        vllm_mlx_version=_optional_version("vllm-mlx"),
        mlx_audio_version=_optional_version("mlx-audio"),
    )
