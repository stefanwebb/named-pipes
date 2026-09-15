# named_pipes.ardy

Client for the `ardy` interface — autoregressive motion diffusion inference over a named pipe.

Install the extra for numpy: `pip install -e ".[ardy]"`.

## Division of labour

The server is a **stateless evaluator**. It holds the weights and answers four commands. It remembers nothing between calls.

The **client owns all session state**: the hybrid history tokens, the accumulated world translation, the first-frame heading, and the denoising loop itself.

That split buys three things:

- the server can restart, or be swapped for a different checkpoint, without losing a take
- one loaded model serves many clients, each with its own characters in flight
- a client can keep several independent sessions against one server (`client.session("npc_3")`)

The cost is chattiness: a full generation is one `denoise` round trip per timestep. On a local FIFO that is roughly 20–80 µs each, against a forward pass measured in milliseconds.

## Commands

| Command | Args | Returns |
|---|---|---|
| `model_info` | — | Model dimensions, so a stateful client can size its own tensors |
| `tokenize` | `motion` | Explicit motion frames → hybrid tokens |
| `detokenize` | `tokens` | Hybrid tokens → explicit motion frames |
| `requantize` | `latent` | Re-quantize latent body channels after the client recenters history |
| `denoise` | `x`, `t`, masks, conditioning | One sampler step; returns `x_{t-1}` |

Every command takes an optional `req_id`, which the server **must** echo on the response event so the client can correlate replies. Errors come back as an `error` event carrying the same `req_id`.

## Tensors on the wire

Tensor arguments and fields are JSON objects:

```json
{"b64": "<base64 of little-endian bytes>", "shape": [1, 10, 148], "dtype": "float32"}
```

`float64` is narrowed to `float32` on encode — motion data does not need the precision and it halves every payload. Allowed dtypes: `float32`, `float64`, `int64`, `int32`, `uint8`, `bool`.

## Usage

```python
import numpy as np
from named_pipes.ardy import ArdyClient

with ArdyClient() as client:
    info = client.model_info()
    session = client.new_session("hero")

    # conditioning is the caller's business; the client just carries it
    session.text_feat = text_feat
    session.text_pad_mask = text_pad_mask

    x = np.random.standard_normal(
        (1, info.num_generation_tokens, info.token_dim)
    ).astype(np.float32)

    x = client.denoise_loop(
        x,
        info.num_base_steps,
        text_feat=session.text_feat,
        text_pad_mask=session.text_pad_mask,
        masks=masks,
        first_heading_angle=session.first_heading_angle,
        cfg_weight=(2.0, 2.0),          # (text, constraint)
    )

    session.append_tokens(x, info.num_frames_per_token)
    motion = client.detokenize(session.history)
```

`denoise_loop` takes an optional `progress=callable(step, total)`.

To continue a take, pass `session.history_window(max_tokens)` as the history portion of the next window — the equivalent of the demo's History Crop Length. A short window adapts to a new prompt quickly; a long one gives smoother motion.

## Classes

### `ArdyClient(name="ardy", timeout=60.0)`

Extends `ToolClient`. All commands are blocking request/response, correlated by `req_id`, so the denoising loop reads as straight-line code. Event handlers registered with `@client.on(...)` still fire for anything the server broadcasts without a `req_id`.

Closing the client fails any in-flight request rather than leaving a thread parked on its timeout.

### `ArdySession`

Client-owned state for one character: `history`, `global_transl`, `first_heading_angle`, `frames_emitted`, plus `text_feat` / `text_pad_mask` for convenience and a free-form `meta` dict.

Helpers: `reset()`, `append_tokens(tokens, frames_per_token)`, `history_window(max_tokens)`.

### `ModelInfo`

Server-reported dimensions, with derived properties `token_dim` (`nframe_root_dim + latent_embedding_dim`), `num_generation_tokens` and `horizon_seconds`.

## Exceptions

- `ArdyError` — the server replied with an `error` event, or a reply was missing its tensor payload
- `ArdyTimeout` — no response within the timeout
