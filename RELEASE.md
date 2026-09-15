## New features

- **ARDY motion-diffusion interface (`named_pipes.ardy`)** — `ArdyServer` serves NVIDIA ARDY autoregressive motion-diffusion inference over a named pipe as a stateless evaluator with five commands: `model_info`, `tokenize`, `detokenize`, `requantize`, and `denoise` (one sampler step). No text encoder is loaded, so the process stays near the ~0.8 GB motion model; `text_feat` is supplied by the caller. Model loading is inlined from the checkpoint's Hydra config so the server imports neither Hydra nor OmegaConf. Launch with `python -m named_pipes.ardy.launch`
- **`ArdyClient` / `ArdySession`** — the client owns all session state (hybrid history tokens, accumulated world translation, first-frame heading) and runs the denoising loop itself via `denoise_loop`, so one loaded model serves many characters and the server can be restarted mid-take. Blocking request/response correlated by `req_id`; tensors travel as base64 little-endian payloads with shape/dtype
- **`ARDY` interface spec** registered in `named_pipes.interfaces`, driving the TUI Messenger's command UI
- **mlx_lm chat backend** — `ChatServer` gains `Backend.MLX_LM` with streaming via `stream_generate`; HuggingFace kwargs (`max_new_tokens`, `do_sample`) are remapped to mlx_lm conventions. `mlx-community/Qwen3.5-2B-OptiQ-4bit` is registered as the default Mac chat model, and `ChatConfig` / the TUI launcher default to it with `max_tokens=4096`
- **`named-pipes[ardy]` extra** (numpy)

## Improvements

- **Transport robustness** — `TextNamedPipe` now reassembles messages larger than one atomic pipe write (a non-blocking `readline()` can return a torn line while a large payload is still being written) and discards malformed JSON with a logged preview instead of letting a `JSONDecodeError` kill the listener thread. This affects every interface

## Infrastructure / Documentation

- `named_pipes/ardy/README.md` and `HELP.md` document the protocol, wire format, and client/server division of labour
- `src/examples/ardy_stub_server.py` stub for exercising the client without the `ardy` package; `tests/test_ardy_client.py`
- Scratch assets: CoreSkeleton27 and Unity-humanoid joint-hierarchy SVG diagrams, FBX build/verify scripts
- Terminal AppleScripts, Claude Code notification hooks, and Moonshine TTS scratch
