# named_pipes.stt.voxtral

Vendored Voxtral real-time speech-to-text implementation for Apple Silicon (MLX). Provides the streaming transcription engine used by `named_pipes.stt.STTServer`.

## Top-Level API

### `stream_transcribe(config, on_token, on_speaking_started, on_speaking_finished, on_ready, stop_event)`

Main entry point for real-time streaming transcription. Runs the microphone capture, VAD, and decoder loop until `stop_event` is set.

| Parameter | Type | Description |
|---|---|---|
| `config` | `STTConfig` | Model path, temperature, VAD thresholds |
| `on_token` | `Callable[[str], None]` | Called with each decoded token text |
| `on_speaking_started` | `Callable[[], None]` | Called when VAD detects speech onset |
| `on_speaking_finished` | `Callable[[], None]` | Called when VAD detects speech offset |
| `on_ready` | `Callable[[], None]` | Called once models are loaded and the mic stream is open |
| `stop_event` | `threading.Event` | Set to shut down gracefully |

### `generate(model, tokenizer, audio_path)`

Offline inference for a single audio file. Returns the full transcription string.

### `load_model(model_path)` → `(VoxtralRealtime, tokenizer, config)`

Download (if needed) and load model weights, tokenizer, and config.

### `download_model(model_path)`

Download model weights from the Hugging Face Hub.

## Model Architecture

`VoxtralRealtime` is a multimodal encoder-decoder combining a causal audio encoder with an autoregressive language model decoder.

```
raw audio (16 kHz)
    │
    ▼
log-mel spectrogram (128 bins)
    │
    ▼
CausalWhisperEncoder
  ├─ 2× causal convolutions (stride 2, stride 1) → 1280-dim frames
  └─ transformer layers with RotatingKVCache + RoPE
    │
    ▼ 1280-dim audio embeddings
AudioLanguageAdapter (5120 → 3072 linear projection)
    │
    ▼ 3072-dim language-space embeddings
LanguageModel decoder (grouped-query attention, AdaptiveNorm)
    │
    ▼ token logits → greedy / sampled tokens
```

### Key Classes

| Class | File | Description |
|---|---|---|
| `VoxtralRealtime` | `model.py` | Top-level multimodal model |
| `CausalWhisperEncoder` | `encoder.py` | Incremental causal audio encoder |
| `EncoderAttention` | `encoder.py` | Encoder self-attention with RoPE |
| `EncoderSwiGLU` | `encoder.py` | Encoder feedforward (SwiGLU activation) |
| `LanguageModel` | `language_model.py` | Autoregressive LLM decoder |
| `DecoderAttention` | `language_model.py` | Decoder attention with KV cache |
| `AdaptiveNorm` | `language_model.py` | RMSNorm conditioned on time embeddings |
| `TimeEmbedding` | `model.py` | Sinusoidal delay-token embeddings |
| `RotatingKVCache` | `cache.py` | Sliding-window KV cache for streaming |

## Streaming Loop (`stream.py`)

The streaming loop runs on the thread spawned by `STTServer`:

1. Open a `sounddevice` input stream at 16 kHz.
2. Buffer incoming audio frames.
3. Run Silero VAD on each chunk.
4. On speech onset, pre-roll buffered audio and begin feeding the encoder.
5. Run the decoder incrementally — call `on_token` for each emitted token.
6. On speech offset, call `on_speaking_finished` and reset the KV cache for the next utterance.

**Pre-roll buffer** — a short window of audio recorded before VAD fires is prepended to each utterance so the first syllables are not missed.

## Audio Processing (`audio.py`)

| Function | Description |
|---|---|
| `log_mel_spectrogram(audio)` | Slaney-style 128-bin mel spectrogram at 16 kHz |
| `pad_audio(frames)` | Left-pad (32 tokens) + right-pad (17 tokens + alignment) for streaming inference |
| `load_audio(path)` | Load a WAV file and resample to 16 kHz |

`SAMPLES_PER_TOKEN = 1280` — one audio token represents 1280 samples (80 ms at 16 kHz), derived from `hop_length × conv_stride × downsample`.

## KV Cache (`cache.py`)

`RotatingKVCache` implements a fixed-size sliding window over the encoder's attention context. When the cache is full, old entries are dropped in temporal order. Supports:

- In-place update mode (for steady-state streaming)
- Concatenation mode (for initial fill)
- Configurable maximum size (default 100 k positions)

## Weight Loading (`weights.py`)

Regex-based weight remapping adapts HuggingFace checkpoint keys to the MLX class attribute hierarchy. `load_model()` handles download, remapping, and quantisation (if applicable).
