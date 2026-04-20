# stt — real-time speech-to-text server

Captures audio from the default microphone and broadcasts transcribed tokens in real time using **Voxtral Mini 4B Realtime** (MLX backend). Speech onset and end are detected with Silero VAD.

Pipe: `/tmp/tool-stt`

## Starting the server

```bash
conda activate named-pipes
cpipe --serve stt
```

Model load takes several seconds. When ready the server prints:

```
STT server listening on /tmp/tool-stt ...
```

## Commands

### Built-in (all ToolServer instances support these)

| Command | Description |
|---|---|
| `ping` | Health check — responds with `pong` event |
| `get_state` | Current server state (e.g. `running`) |
| `get_description` | One-line description of the server |
| `get_help` | Full help text |
| `get_config` | Current server configuration |
| `stop` | Shut the server down gracefully |

The STT server has no custom request commands — it is producer-only. Transcription output is broadcast to all subscribers automatically while audio is detected.

## States

The server broadcasts `{"event": "state_changed", "state": "<value>"}` to all subscribers on every transition. The `get_state` command returns the current state.

| State | When |
|-------|------|
| `running` | Server process started |
| `loading` | ASR and VAD models are being loaded |
| `listening` | Models loaded; waiting for speech to begin |
| `transcribing` | Speech detected; decoding tokens |
| `stopping` | `stop` command received; shutting down |
| `error` | Unrecoverable error |

## Broadcast events

While subscribed, a client receives the following events. State transitions (`state_changed`) are interleaved with transcription events:

| Event | When |
|---|---|
| `{"event": "state_changed", "state": "<value>"}` | Server state changes (see States above) |

Per utterance:

| Event | When |
|---|---|
| `{"event": "speech_start"}` | VAD detects start of speech |
| `{"event": "token", "text": "<token>"}` | Per token emitted by the decoder |
| `{"event": "speech_end"}` | End of speech detected; all tokens for the utterance have been sent |

Tokens are sub-word pieces from the Voxtral tokenizer. To reconstruct whole words, concatenate consecutive `token` texts between a `speech_start` / `speech_end` pair.

## Examples

```bash
# Check the server is running
cpipe --list

# Get a one-line description
cpipe stt get_description

# Subscribe and listen — prints transcription to stdout until Ctrl+C
cpipe stt subscribe --no-wait

# Shut down the server
cpipe stt stop
```

> **Note:** `cpipe` is designed for one-shot command/response use. For continuous transcription in production code, subscribe directly using `STTServer` or `TextNamedPipe` in a Python client (see `src/examples/stt_client.py`).
