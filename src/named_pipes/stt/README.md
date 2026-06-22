# named_pipes.stt

Real-time speech-to-text transcription server over named pipes. Captures audio from a microphone and broadcasts transcribed text to all subscribers using [Moonshine Voice](https://github.com/moonshine-ai/moonshine).

Pipe: `/tmp/tool-stt`

## Classes

### `STTServer`

`ToolServer` subclass. Implements the `stt` interface (`named_pipes.interfaces.stt.STT`).

The Moonshine model is loaded eagerly on construction, but the microphone
stream is **not** opened until a `start` command is received. Before
`start`, clients can call `list_devices` / `get_device` / `set_device` to
choose an input device.

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
| `speech_start` | A new transcription line starts |
| `speech` | The current line's text is updated; `text` field holds the running transcript |
| `speech_end` | The current line completes |

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
| `language` | `str` | `"en"` | Moonshine model language |
| `device` | `int \| None` | `None` | Initial input device (`None` = host default) |
| `update_interval` | `float` | `0.5` | Seconds between incremental transcript updates |
| `verbose` | `bool` | `True` | Print loading/status messages to stdout |

---

### `STTState`

```python
class STTState(Enum):
    LOADING      = "loading"
    READY        = "ready"        # model loaded, mic not yet started
    LISTENING    = "listening"
    TRANSCRIBING = "transcribing"
    PAUSED       = "paused"
    ERROR        = "error"
```

## Launching

### From Python

```python
from named_pipes.stt import STTServer, STTConfig

config = STTConfig(language="en")
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
← {"event": "state_changed", "state": "listening"}
← {"event": "speech_start"}
← {"event": "speech", "text": "Hello"}
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

## Legacy backend

`named_pipes/stt/server_voxtral.py` holds the previous Voxtral-based
implementation (producer-only, per-token `token` events via Silero VAD +
the streaming Voxtral decoder). It is not wired into `__init__.py` /
`launch.py` and is kept for reference only.
