# named_pipes.tts

Real-time text-to-speech synthesis server over named pipes. Accepts streamed text from clients, detects sentence boundaries, synthesises audio with Kokoro (via `mlx-audio`), and plays it through the system audio output.

Pipe: `/tmp/tool-tts`

## Classes

### `TTSServer`

`ToolServer` subclass. Implements the `TTS` interface on top of base `ToolServer` commands.

**Supported commands**

| Command | Description |
|---|---|
| `text` | Append text to the synthesis buffer; sentences are spoken as they complete |
| `flush` | Force synthesis of any remaining buffered text (no sentence boundary required) |
| `is_speaking` | Query whether audio is currently playing; responds with `is_speaking` event |

The server emits `speech_start` and `speech_end` broadcast events to all subscribers when audio playback begins and ends.

---

### `TTSConfig`

Pydantic model holding server configuration.

| Field | Type | Default | Description |
|---|---|---|---|
| `model` | `str` | `"mlx-community/Kokoro-82M-bf16"` | mlx-audio model identifier |
| `voice` | `str` | `"af_heart"` | Kokoro voice name |
| `sample_rate` | `int` | `24000` | Audio sample rate (Hz) |
| `blocksize` | `int` | `2048` | `sounddevice` callback block size (samples) |

---

### `TTSState`

```python
class TTSState(Enum):
    LOADING      = "loading"
    IDLE         = "idle"
    SYNTHESIZING = "synthesizing"
    ERROR        = "error"
```

## Audio Pipeline

```
text commands → [sentence splitter] → sentence queue
              → [TTS worker thread] → audio chunk queue
              → [sounddevice callback] → speakers
```

**Sentence splitter** — buffers incoming text and enqueues complete sentences when it detects a sentence-ending punctuation mark (`. ! ?`) followed by whitespace.

**TTS worker thread** — dequeues sentences, calls the Kokoro model to synthesise raw PCM frames, and pushes them onto the audio chunk queue.

**Audio callback** — runs on the `sounddevice.OutputStream` thread at playback rate. Drains the audio chunk queue frame by frame and pads underruns with silence to keep the stream continuous.

The `speech_start` event is broadcast when the first audio frame starts playing. `speech_end` is broadcast when the queue drains and silence padding begins.

## Launching

### From Python

```python
from named_pipes.tts import TTSServer, TTSConfig

config = TTSConfig(voice="af_heart")
server = TTSServer(config)
server.start()  # blocks until stop
```

### From the CLI

```bash
cpipe --serve tts
```

### Via `launch.py`

`named_pipes.tts.launch` is the subprocess entry point used by the TUI. It reads a JSON-serialised `TTSConfig` from `argv[1]`.

## Wire Example

```
→ {"pid": 1234, "cmd": "text", "text": "Hello, world."}
  (audio plays through speakers; no pipe response)
→ {"pid": 1234, "cmd": "flush"}
← {"event": "speech_start"}     (broadcast to all subscribers)
← {"event": "speech_end"}       (broadcast when audio finishes)
```

`text` and `flush` do not send a reply to the caller. Use `--no-wait` with `cpipe` to avoid a timeout.
