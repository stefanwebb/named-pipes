# named_pipes.stt

Real-time speech-to-text transcription server over named pipes. Captures audio from the default microphone, applies Silero VAD, and broadcasts transcribed tokens to all subscribers using the Voxtral streaming decoder.

Pipe: `/tmp/tool-stt`

## Classes

### `STTServer`

`ToolServer` subclass. Implements the `STT` interface. This server is **producer-only** — it accepts no custom commands beyond the built-in `ToolServer` set. All output is broadcast to subscribers as events.

The transcription worker thread starts automatically on server initialisation.

**Broadcast events**

| Event | When |
|---|---|
| `speech_start` | VAD detects the onset of speech |
| `token` | One transcribed sub-word token; `text` field holds the text |
| `speech_end` | VAD detects the end of speech; all tokens for the utterance have been sent |

Tokens between `speech_start` and `speech_end` form a single utterance. Concatenate their `text` fields to reconstruct the full transcription.

---

### `STTConfig`

Pydantic model holding server configuration.

| Field | Type | Default | Description |
|---|---|---|---|
| `model_path` | `str` | `"mistralai/Voxtral-Mini-4B-2507"` | HuggingFace model identifier |
| `temperature` | `float` | `0.0` | Decoder sampling temperature |
| `vad_onset` | `float` | `0.5` | Silero VAD speech-start threshold |
| `vad_offset` | `float` | `0.35` | Silero VAD speech-end threshold |

---

### `STTState`

```python
class STTState(Enum):
    LOADING      = "loading"
    LISTENING    = "listening"
    TRANSCRIBING = "transcribing"
    ERROR        = "error"
```

## Architecture

The STT worker is launched as a daemon thread during `__init__`. It delegates to `named_pipes.stt.voxtral.stream_transcribe()`, which manages:

- Microphone input via `sounddevice`
- Silero VAD with configurable onset/offset thresholds and pre-roll buffering
- Voxtral streaming decoder with a rotating KV cache
- Per-token callbacks forwarded back to `STTServer` for broadcasting

Shutdown is coordinated via a `threading.Event` stop flag.

## Launching

### From Python

```python
from named_pipes.stt import STTServer, STTConfig

config = STTConfig(vad_onset=0.6)
server = STTServer(config)
server.start()  # blocks until stop
```

### From the CLI

```bash
cpipe --serve stt
```

### Via `launch.py`

`named_pipes.stt.launch` is the subprocess entry point used by the TUI. It reads a JSON-serialised `STTConfig` from `argv[1]`.

## Wire Example

```
(no command sent — server pushes events automatically)
← {"event": "speech_start"}
← {"event": "token", "text": "Hello"}
← {"event": "token", "text": ","}
← {"event": "token", "text": " world"}
← {"event": "token", "text": "."}
← {"event": "speech_end"}
```

For continuous transcription in client code, subscribe directly using `ToolClient` rather than `cpipe` (which is designed for one-shot use):

```python
from named_pipes.tools import ToolClient

with ToolClient("stt") as client:
    client.on("token", lambda m: print(m["text"], end="", flush=True))
    client.on("speech_end", lambda _: print())
    client.wait()  # block until server stops
```
