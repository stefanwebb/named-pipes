"""Convert Voxtral weights to voxmlx format, with optional quantization and HF upload."""

import argparse
import json
import shutil
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
from mlx.utils import tree_flatten, tree_reduce

from .model import VoxtralRealtime
from .weights import download_model, load_model, _remap_name, _is_conv_weight


def _get_total_parameters(model):
    leaf_modules = tree_flatten(
        model.leaf_modules(), is_leaf=lambda m: isinstance(m, nn.Module)
    )

    def nparams(m):
        if hasattr(m, "bits"):
            n = 0 if not hasattr(m, "bias") else m.bias.size
            return n + m.weight.size * 32 // m.bits
        return sum(v.size for _, v in tree_flatten(m.parameters()))

    return sum(nparams(m) for _, m in leaf_modules)


def _compute_bits_per_weight(model):
    model_bytes = tree_reduce(
        lambda acc, x: acc + x.nbytes if isinstance(x, mx.array) else acc, model, 0
    )
    return model_bytes * 8 / _get_total_parameters(model)


def _make_shards(weights: dict, max_file_size_gb: int = 5) -> list:
    max_file_size_bytes = max_file_size_gb << 30
    shards = []
    shard, shard_size = {}, 0
    for k, v in weights.items():
        if shard_size + v.nbytes > max_file_size_bytes:
            shards.append(shard)
            shard, shard_size = {}, 0
        shard[k] = v
        shard_size += v.nbytes
    shards.append(shard)
    return shards


def _save_model(save_path: Path, model: nn.Module):
    save_path.mkdir(parents=True, exist_ok=True)

    weights = dict(tree_flatten(model.parameters()))
    shards = _make_shards(weights)
    shards_count = len(shards)
    shard_file_format = (
        "model-{:05d}-of-{:05d}.safetensors"
        if shards_count > 1
        else "model.safetensors"
    )

    total_size = sum(v.nbytes for v in weights.values())
    index_data = {
        "metadata": {
            "total_size": total_size,
            "total_parameters": _get_total_parameters(model),
        },
        "weight_map": {},
    }

    weights.clear()
    del weights

    for i in range(len(shards)):
        shard = shards[i]
        shards[i] = None
        shard_name = shard_file_format.format(i + 1, shards_count)
        shard_path = save_path / shard_name

        mx.save_safetensors(str(shard_path), shard, metadata={"format": "mlx"})

        for weight_name in shard.keys():
            index_data["weight_map"][weight_name] = shard_name
        del shard

    index_data["weight_map"] = {
        k: index_data["weight_map"][k] for k in sorted(index_data["weight_map"])
    }

    with open(save_path / "model.safetensors.index.json", "w") as f:
        json.dump(index_data, f, indent=4)


def _quantize_model(model: nn.Module, group_size: int = 64, bits: int = 4):
    def predicate(path, module):
        if not hasattr(module, "to_quantized"):
            return False
        if module.weight.shape[-1] % group_size != 0:
            return False
        return True

    nn.quantize(model, group_size=group_size, bits=bits, class_predicate=predicate)
    bpw = _compute_bits_per_weight(model)
    print(f"[INFO] Quantized model with {bpw:.3f} bits per weight.")
    return {"group_size": group_size, "bits": bits}


def _upload_to_hub(path: str, upload_repo: str, hf_path: str | None = None):
    from huggingface_hub import HfApi, ModelCard, ModelCardData

    card_path = Path(path) / "README.md"
    if card_path.exists():
        card = ModelCard.load(card_path)
    elif hf_path is not None:
        card = ModelCard.load(hf_path)
    else:
        card = ModelCard.from_template(ModelCardData(language="en"))

    card.data.library_name = "mlx"
    card.data.pipeline_tag = "automatic-speech-recognition"
    if card.data.tags is None:
        card.data.tags = ["mlx"]
    elif "mlx" not in card.data.tags:
        card.data.tags += ["mlx"]
    if hf_path is not None:
        card.data.base_model = hf_path

    provenance = ""
    if hf_path is not None:
        provenance = (
            f"This model [{upload_repo}](https://huggingface.co/{upload_repo}) was "
            f"converted to MLX format from [{hf_path}](https://huggingface.co/{hf_path}) "
            f"using [voxmlx](https://github.com/awnihannun/voxmlx)."
        )

    card.text = f"""# {upload_repo}

{provenance}

## Use with voxmlx

```bash
pip install voxmlx
```

```python
from voxmlx import transcribe

text = transcribe("audio.flac", model_path="{upload_repo}")
print(text)
```
"""
    card.save(card_path)

    api = HfApi()
    api.create_repo(repo_id=upload_repo, exist_ok=True)
    api.upload_large_folder(
        folder_path=path,
        repo_id=upload_repo,
        repo_type="model",
    )
    print(f"Upload successful: https://huggingface.co/{upload_repo}")


def convert(
    hf_path: str = "mistralai/Voxtral-Mini-4B-Realtime-2602",
    mlx_path: str = "mlx_model",
    quantize: bool = False,
    q_group_size: int = 64,
    q_bits: int = 4,
    dtype: str | None = None,
    upload_repo: str | None = None,
):
    mlx_path = Path(mlx_path)
    if mlx_path.exists():
        raise ValueError(f"Output path {mlx_path} already exists.")

    print(f"[INFO] Loading {hf_path}")
    src_path = download_model(hf_path)
    model, config = load_model(src_path)

    # Cast dtype if requested
    if dtype is not None:
        dt = getattr(mx, dtype)
        weights = dict(tree_flatten(model.parameters()))
        weights = {k: v.astype(dt) if v.dtype in (mx.float32, mx.float16, mx.bfloat16) else v for k, v in weights.items()}
        model.load_weights(list(weights.items()))
        mx.eval(model.parameters())

    # Quantize
    quant_config = None
    if quantize:
        quant_config = _quantize_model(model, q_group_size, q_bits)

    # Save
    print(f"[INFO] Saving to {mlx_path}")
    _save_model(mlx_path, model)

    # Save config
    save_config = dict(config)
    if quant_config is not None:
        save_config["quantization"] = quant_config
    with open(mlx_path / "config.json", "w") as f:
        json.dump(dict(sorted(save_config.items())), f, indent=4)

    # Copy tekken.json
    shutil.copy(src_path / "tekken.json", mlx_path / "tekken.json")

    bpw = _compute_bits_per_weight(model)
    total_params = _get_total_parameters(model)
    print(f"[INFO] Total parameters: {total_params:,}")
    print(f"[INFO] Bits per weight: {bpw:.3f}")

    # Upload
    if upload_repo is not None:
        _upload_to_hub(str(mlx_path), upload_repo, hf_path)


def main():
    parser = argparse.ArgumentParser(description="Convert Voxtral to voxmlx format")
    parser.add_argument(
        "--hf-path",
        default="mistralai/Voxtral-Mini-4B-Realtime-2602",
        help="HuggingFace model ID or local path (default: mistralai/Voxtral-Mini-4B-Realtime-2602)",
    )
    parser.add_argument(
        "--mlx-path",
        default="mlx_model",
        help="Output directory (default: mlx_model)",
    )
    parser.add_argument(
        "-q", "--quantize",
        action="store_true",
        help="Quantize the model",
    )
    parser.add_argument(
        "--group-size",
        type=int,
        default=64,
        help="Quantization group size (default: 64)",
    )
    parser.add_argument(
        "--bits",
        type=int,
        default=4,
        help="Bits per weight for quantization (default: 4)",
    )
    parser.add_argument(
        "--dtype",
        choices=["float16", "bfloat16", "float32"],
        default=None,
        help="Cast weights to this dtype before saving",
    )
    parser.add_argument(
        "--upload-repo",
        default=None,
        help="HuggingFace repo to upload the converted model",
    )
    args = parser.parse_args()

    convert(
        hf_path=args.hf_path,
        mlx_path=args.mlx_path,
        quantize=args.quantize,
        q_group_size=args.group_size,
        q_bits=args.bits,
        dtype=args.dtype,
        upload_repo=args.upload_repo,
    )


if __name__ == "__main__":
    main()
