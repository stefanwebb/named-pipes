# ARDY server

Stateless ARDY motion-diffusion inference over a named pipe.

The server holds the weights and evaluates forward passes. It remembers nothing
between calls — the client owns the history tokens, the world translation, the
heading and the denoising loop.

**No text encoder is loaded.** `denoise` takes `text_feat` as an argument, so
prompt embedding happens elsewhere. This keeps the process near the size of the
motion model (~0.8 GB) rather than the ~17 GB it would need with LLM2Vec resident.

## Launch

```bash
python -m named_pipes.ardy.launch
python -m named_pipes.ardy.launch '{"model": "nvidia/ARDY-Core-RP-20FPS-Horizon8", "device": "mps"}'
python -m named_pipes.ardy.launch '{"model": "/path/to/checkpoint-folder"}'
```

Config fields: `name` (pipe name, default `ardy`), `model` (a Hugging Face repo
id, default `nvidia/ARDY-Core-RP-20FPS-Horizon40`, downloaded and cached on
first use — or the path of a local checkpoint folder), and `device` (default
auto: cuda, then mps, then cpu; `ARDY_DEVICE` is honoured).

## Commands

| Command | Args | Reply event |
|---|---|---|
| `model_info` | — | `model_info` — dimensions for a stateful client |
| `tokenize` | `motion` `[B, T, D]` | `tokenized` — hybrid tokens |
| `detokenize` | `tokens` `[B, N, D]` | `detokenized` — explicit motion |
| `requantize` | `latent` | `requantized` — re-quantized latents |
| `denoise` | `x`, `t`, `num_denoising_steps`, `text_feat`, `text_pad_mask`, `masks`, `first_heading_angle`, optional `motion_mask`, `observed_motion`, `cfg_weight`, `cfg_type` | `denoised` — `x` after one sampler step |

Every command accepts a `req_id`, echoed on the reply so clients can correlate.
Failures come back as an `error` event carrying the same `req_id`.

Tensors are `{"b64": ..., "shape": [...], "dtype": "float32"}`.

`masks` bundles the six mask tensors — `history_mask`, `generation_mask`,
`future_mask`, `history_token_mask`, `generation_token_mask`,
`future_token_mask` — plus `history_len`, `generation_len` and `future_len`,
each an integer or a per-batch array.

## Notes

- `T` for `tokenize` must be a multiple of `num_frames_per_token`.
- `requantize` errors unless the autoencoder quantizes; check
  `encode_with_quantization` from `model_info` first.
- Commands are serialized: one forward pass at a time. MPS is not thread-safe,
  and overlapping passes on a single model buys nothing.
- Requires the `ardy` package on the path. It is not on PyPI — install it into
  the same environment separately.
