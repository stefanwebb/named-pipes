import json
import re
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
from huggingface_hub import snapshot_download

from .model import VoxtralRealtime


def download_model(model_id: str = "mistralai/Voxtral-Mini-4B-Realtime-2602") -> Path:
    path = snapshot_download(
        model_id,
        allow_patterns=[
            "consolidated.safetensors",
            "model*.safetensors",
            "model.safetensors.index.json",
            "params.json",
            "config.json",
            "tekken.json",
        ],
    )
    return Path(path)


# Weight name remapping patterns: (regex, replacement)
_REMAP_PATTERNS = [
    # Encoder conv layers
    (r"whisper_encoder\.conv_layers\.0\.conv\.(.*)", r"encoder.conv1.\1"),
    (r"whisper_encoder\.conv_layers\.1\.conv\.(.*)", r"encoder.conv2.\1"),
    # Encoder transformer layers
    (r"whisper_encoder\.transformer\.layers\.(\d+)\.attention\.wq\.(.*)", r"encoder.layers.\1.attention.q_proj.\2"),
    (r"whisper_encoder\.transformer\.layers\.(\d+)\.attention\.wk\.(.*)", r"encoder.layers.\1.attention.k_proj.\2"),
    (r"whisper_encoder\.transformer\.layers\.(\d+)\.attention\.wv\.(.*)", r"encoder.layers.\1.attention.v_proj.\2"),
    (r"whisper_encoder\.transformer\.layers\.(\d+)\.attention\.wo\.(.*)", r"encoder.layers.\1.attention.o_proj.\2"),
    (r"whisper_encoder\.transformer\.layers\.(\d+)\.attention_norm\.(.*)", r"encoder.layers.\1.attn_norm.\2"),
    (r"whisper_encoder\.transformer\.layers\.(\d+)\.feed_forward\.w1\.(.*)", r"encoder.layers.\1.mlp.gate_proj.\2"),
    (r"whisper_encoder\.transformer\.layers\.(\d+)\.feed_forward\.w2\.(.*)", r"encoder.layers.\1.mlp.down_proj.\2"),
    (r"whisper_encoder\.transformer\.layers\.(\d+)\.feed_forward\.w3\.(.*)", r"encoder.layers.\1.mlp.up_proj.\2"),
    (r"whisper_encoder\.transformer\.layers\.(\d+)\.ffn_norm\.(.*)", r"encoder.layers.\1.ffn_norm.\2"),
    (r"whisper_encoder\.transformer\.norm\.(.*)", r"encoder.norm.\1"),
    # Adapter
    (r"audio_language_projection\.0\.weight", r"adapter.w_in.weight"),
    (r"audio_language_projection\.2\.weight", r"adapter.w_out.weight"),
    # Language model embedding
    (r"tok_embeddings\.weight", r"language_model.embed_tokens.weight"),
    # Language model layers
    (r"layers\.(\d+)\.attention\.wq\.weight", r"language_model.layers.\1.attention.q_proj.weight"),
    (r"layers\.(\d+)\.attention\.wk\.weight", r"language_model.layers.\1.attention.k_proj.weight"),
    (r"layers\.(\d+)\.attention\.wv\.weight", r"language_model.layers.\1.attention.v_proj.weight"),
    (r"layers\.(\d+)\.attention\.wo\.weight", r"language_model.layers.\1.attention.o_proj.weight"),
    (r"layers\.(\d+)\.attention_norm\.weight", r"language_model.layers.\1.attn_norm.weight"),
    (r"layers\.(\d+)\.feed_forward\.w1\.weight", r"language_model.layers.\1.mlp.gate_proj.weight"),
    (r"layers\.(\d+)\.feed_forward\.w2\.weight", r"language_model.layers.\1.mlp.down_proj.weight"),
    (r"layers\.(\d+)\.feed_forward\.w3\.weight", r"language_model.layers.\1.mlp.up_proj.weight"),
    (r"layers\.(\d+)\.ffn_norm\.weight", r"language_model.layers.\1.ffn_norm.weight"),
    (r"layers\.(\d+)\.ada_rms_norm_t_cond\.0\.weight", r"language_model.layers.\1.ada_norm.linear_in.weight"),
    (r"layers\.(\d+)\.ada_rms_norm_t_cond\.2\.weight", r"language_model.layers.\1.ada_norm.linear_out.weight"),
    # Language model output norm
    (r"norm\.weight", r"language_model.norm.weight"),
]


def _remap_name(name: str) -> str | None:
    # Strip known prefixes before matching
    name = re.sub(r"^(mm_streams_embeddings\.embedding_module|mm_whisper_embeddings)\.", "", name)
    for pattern, replacement in _REMAP_PATTERNS:
        new_name, n = re.subn(f"^{pattern}$", replacement, name)
        if n > 0:
            return new_name
    return None


def _is_conv_weight(name: str) -> bool:
    return ("conv1.weight" in name or "conv2.weight" in name) and "bias" not in name


def _is_converted_format(model_path: Path) -> bool:
    """Check if the model is in voxmlx converted format (has config.json + model.safetensors)."""
    return (model_path / "config.json").exists() and not (model_path / "consolidated.safetensors").exists()


def _load_converted(model_path: Path) -> tuple[VoxtralRealtime, dict]:
    """Load a model saved in voxmlx converted format."""
    with open(model_path / "config.json") as f:
        config = json.load(f)

    quant_config = config.get("quantization")
    model = VoxtralRealtime(config)

    # Apply quantization structure before loading weights
    if quant_config is not None:
        group_size = quant_config["group_size"]

        def predicate(path, module):
            if not hasattr(module, "to_quantized"):
                return False
            if module.weight.shape[-1] % group_size != 0:
                return False
            return True

        nn.quantize(
            model,
            group_size=group_size,
            bits=quant_config["bits"],
            class_predicate=predicate,
        )

    # Load weights — either single file or sharded
    index_path = model_path / "model.safetensors.index.json"
    if index_path.exists():
        with open(index_path) as f:
            index = json.load(f)
        shard_files = sorted(set(index["weight_map"].values()))
        weights = {}
        for shard_file in shard_files:
            weights.update(mx.load(str(model_path / shard_file)))
    else:
        weights = mx.load(str(model_path / "model.safetensors"))

    model.load_weights(list(weights.items()))
    mx.eval(model.parameters())

    return model, config


def _load_original(model_path: Path) -> tuple[VoxtralRealtime, dict]:
    """Load a model in the original Mistral format (consolidated.safetensors + params.json)."""
    with open(model_path / "params.json") as f:
        config = json.load(f)

    model = VoxtralRealtime(config)

    weights = mx.load(str(model_path / "consolidated.safetensors"))

    remapped = {}
    skipped = []
    for name, tensor in weights.items():
        if name == "output.weight":
            continue

        new_name = _remap_name(name)
        if new_name is None:
            skipped.append(name)
            continue

        # Transpose conv weights: PyTorch [C_out, C_in, K] -> MLX [C_out, K, C_in]
        if _is_conv_weight(new_name):
            tensor = mx.swapaxes(tensor, 1, 2)

        remapped[new_name] = tensor

    if skipped:
        print(f"Warning: skipped {len(skipped)} unrecognized weights: {skipped[:5]}...")

    model.load_weights(list(remapped.items()))
    mx.eval(model.parameters())

    return model, config


def load_model(model_path: str | Path) -> tuple[VoxtralRealtime, dict]:
    model_path = Path(model_path)
    if _is_converted_format(model_path):
        return _load_converted(model_path)
    return _load_original(model_path)
