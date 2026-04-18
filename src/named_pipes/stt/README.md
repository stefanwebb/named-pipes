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

### Built-in (all ToolNamedPipe servers support these)

| Command | Description |
|---|---|
| `ping` | Health check — responds with `pong` |
| `status` | Current server state (e.g. `running`) |
| `description` | One-line description of the server |
| `help` | Full help text |
| `stop` | Shut the server down gracefully |

The STT server has no custom request commands — it is producer-only. Transcription output is broadcast to all subscribers automatically while audio is detected.

## Broadcast messages

While subscribed, a client receives the following messages for each utterance:

| Message | When |
|---|---|
| `{"event": "speech_start"}` | VAD detects start of speech |
| `{"result": "<token>"}` | Per token emitted by the decoder |
| `{"event": "speech_end"}` | End of speech detected; all tokens for the utterance have been sent |

Tokens are sub-word pieces from the Voxtral tokenizer. To reconstruct whole words, concatenate consecutive `result` strings between a `speech_start` / `speech_end` pair.

## Examples

```bash
# Check the server is running
cpipe --list

# Get a one-line description
cpipe stt description

# Subscribe and listen — prints transcription to stdout until Ctrl+C
cpipe stt subscribe --no-wait

# Shut down the server
cpipe stt stop
```

> **Note:** `cpipe` is designed for one-shot command/response use. For continuous transcription in production code, subscribe directly using `STTNamedPipe` or `TextNamedPipe` in a Python client (see `src/examples/stt_client.py`).
