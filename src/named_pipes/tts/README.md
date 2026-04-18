# tts — real-time text-to-speech server

Synthesises speech in real time from streamed text tokens using **Kokoro-82M** (mlx-audio). Text is buffered and split on sentence boundaries; each sentence is synthesised and played through the system audio output as it arrives.

Pipe: `/tmp/tool-tts`

## Starting the server

```bash
conda activate named-pipes
cpipe --serve tts
```

The server loads the model on startup, then prints:

```
[TTS] Loading model 'mlx-community/Kokoro-82M-bf16'…
[TTS] Audio stream started.
TTS server listening on /tmp/tool-tts ...
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

### `text` — append tokens to the synthesis buffer

Appends text to the internal buffer. When a sentence boundary (`.`, `!`, or `?` followed by whitespace) is detected, the sentence is synthesised and played automatically. No response is sent.

```bash
cpipe tts text -d "Hello, world."
```

### `flush` — drain the buffer

Forces any remaining buffered text to be synthesised immediately, even if no sentence boundary has been detected. Use this after the last token to ensure the final fragment is spoken. No response is sent.

```bash
cpipe tts flush
```

## Pipeline

```
text commands → [sentence splitter] → sentence queue
              → [TTS worker]        → audio queue
              → [audio callback]    → speakers
```

Audio plays through the system default output device in real time. No audio data is returned over the pipe.

## Examples

```bash
# Check the server is running
cpipe --list

# Get a one-line description
cpipe tts description

# Speak a single sentence
cpipe tts text -d "The quick brown fox jumps over the lazy dog." --no-wait

# Stream multiple tokens then flush (typical LLM integration pattern)
cpipe tts text -d "Once upon a time" --no-wait
cpipe tts text -d " there was a robot." --no-wait
cpipe tts flush --no-wait

# Speak a longer passage
cpipe tts text -d "Hello! How are you today? I hope you are well." --no-wait
cpipe tts flush --no-wait

# Shut down the server
cpipe tts stop
```

> **Note:** `text` and `flush` do not return a response, so use `--no-wait` to avoid a timeout. For LLM-to-TTS pipelines, see `src/examples/tts_client.py`.
