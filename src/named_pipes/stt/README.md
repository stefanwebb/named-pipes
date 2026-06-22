# named_pipes.stt

Real-time speech-to-text transcription server over named pipes. Captures audio from a microphone and broadcasts transcribed text to all subscribers using a vendored Voxtral streaming decoder with Silero VAD.

Pipe: `/tmp/tool-stt`

## Classes

### `STTServer`

`ToolServer` subclass. Implements the `stt` interface (`named_pipes.interfaces.stt.STT`).

The Voxtral model and VAD are loaded lazily, on the first `start` command,
rather than at construction time, so `list_devices` / `get_device` /
`set_device` are available immediately without paying the model-load cost.

**Commands**

| Command | Args | Description |
|---|---|---|
| `start` | — | Start or resume listening on the microphone |
| `pause` | — | Stop listening; finish transcribing audio already received |
| `list_devices` | — | List available audio input devices |
| `get_device` | — | Get the audio input device used by the current stream |
| `set_device` | `device: str` | Set the audio input device (index or name substring) |

**Broadcast events**

| Event | When |
|---|---|
| `speech_start` | VAD detects the onset of speech |
| `token` | One transcribed sub-word token; `text` field holds the fragment |
| `speech` | Each token; `text` field holds the running transcript for the current utterance |
| `speech_end` | VAD detects the end of speech; all tokens for the utterance have been sent |

**Response events**

| Event | Sent in reply to | Fields |
|---|---|---|
| `devices` | `list_devices` | `devices: list` of `{index, name, channels}` |
| `device` | `get_device` / `set_device` | `device: int \| None` |

---

### `STTConfig`

Pydantic model holding server configuration.

| Field | Type | Default | Description |
|---|---|---|---|
| `model_path` | `str` | `"mlx-community/Voxtral-Mini-4B-Realtime-6bit"` | HuggingFace model identifier |
| `temperature` | `float` | `0.0` | Decoder sampling temperature |
| `vad_onset` | `int` | `2` | Consecutive VAD speech frames before starting transcription |
| `vad_offset` | `int` | `32` | Consecutive VAD silence frames before stopping transcription |
| `device` | `int \| None` | `None` | Initial input device (`None` = host default) |
| `verbose` | `bool` | `True` | Print loading/status messages to stdout |
| `align` | `bool` | `False` | Attach per-word forced-alignment timestamps to `speech` events |
| `align_language` | `str` | `"English"` | Language passed to the forced aligner |
| `align_model` | `str` | `"mlx-community/Qwen3-ForcedAligner-0.6B-4bit"` | MLX forced-aligner model id |

---

### `STTState`

```python
class STTState(Enum):
    READY        = "ready"        # constructed, mic not yet started
    LOADING      = "loading"      # model/VAD loading after a start command
    LISTENING    = "listening"
    TRANSCRIBING = "transcribing"
    PAUSED       = "paused"
    ERROR        = "error"
```

## Launching

### From Python

```python
from named_pipes.stt import STTServer, STTConfig

config = STTConfig(vad_onset=2)
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
→ {"pid": 123, "cmd": "list_devices"}
← {"event": "devices", "devices": [{"index": 0, "name": "MacBook Pro Microphone", "channels": 1}]}
→ {"pid": 123, "cmd": "set_device", "device": 0}
← {"event": "device", "device": 0}
→ {"pid": 123, "cmd": "start"}
← {"event": "state_changed", "state": "loading"}
← {"event": "state_changed", "state": "listening"}
← {"event": "speech_start"}
← {"event": "token", "text": "Hello"}
← {"event": "speech", "text": "Hello"}
← {"event": "token", "text": ", world"}
← {"event": "speech", "text": "Hello, world"}
← {"event": "speech_end"}
→ {"pid": 123, "cmd": "pause"}
```

For continuous transcription in client code, subscribe directly using `ToolClient` rather than `cpipe` (which is designed for one-shot use):

```python
from named_pipes.tools import ToolClient

with ToolClient("stt") as client:
    client.send_command("start")
    client.on("speech", lambda m: print(f"\r{m['text']}", end="", flush=True))
    client.on("speech_end", lambda _: print())
    client.wait()  # block until server stops
```

## Per-word timestamps (forced alignment)

Set `align=True` to attach per-word absolute timestamps to `speech` events. The
server re-aligns the utterance-so-far on each word boundary (coalesced, in a
background thread) plus once at `speech_end`, using the MLX
`mlx-community/Qwen3-ForcedAligner-0.6B-4bit` model via `mlx-audio`.

Download the aligner model once:

    hf download mlx-community/Qwen3-ForcedAligner-0.6B-4bit

`speech` events then include a `words` array:

    {"event": "speech", "text": "hello world",
     "words": [{"word": "hello", "start": 1750540000.080, "end": 1750540000.480},
               {"word": "world", "start": 1750540000.560, "end": 1750540000.800}]}

`start`/`end` are absolute Unix epoch seconds (millisecond precision). The
aligner's intrinsic resolution is 80 ms. If alignment is disabled or the model
is unavailable, `speech` events are emitted without `words` and transcription is
unaffected.

## Alternate backend

`named_pipes/stt/server_moonshine.py` holds an alternate implementation of
the same `stt` interface backed by [Moonshine Voice](https://github.com/moonshine-ai/moonshine)
instead of Voxtral. It is not wired into `__init__.py` / `launch.py` (which
both use the Voxtral-backed `server.py`); swap the import to use it.
