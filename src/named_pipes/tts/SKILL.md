# tts — real-time text-to-speech over a named pipe

Synthesises speech in real time from streamed text tokens using **Kokoro-82M** (mlx-audio). Text is buffered and split on sentence boundaries; each sentence is synthesised and played through the system audio output as it arrives.

Pipe: `/tmp/tool-tts`

## Built-in commands

| Command | Request | Response |
|---|---|---|
| `subscribe` | `{"pid": <int>, "cmd": "subscribe"}` | `{"result": "subscribed"}` |
| `unsubscribe` | `{"pid": <int>, "cmd": "unsubscribe"}` | *(none)* |
| `ping` | `{"pid": <int>, "cmd": "ping"}` | `{"result": "pong"}` |
| `status` | `{"pid": <int>, "cmd": "status"}` | `{"result": "<state>"}` e.g. `"running"` |
| `description` | `{"pid": <int>, "cmd": "description"}` | `{"result": "<one-line description>"}` |
| `help` | `{"pid": <int>, "cmd": "help"}` | `{"result": "<this text>"}` |
| `exit` | `{"pid": <int>, "cmd": "exit"}` | `{"result": "exiting"}` broadcast to all subscribers, then server exits |

## TTS commands

### `text` — append tokens to the synthesis buffer

```json
{"pid": 12345, "cmd": "text", "data": "<token or text chunk>"}
```

Appends the token to the internal buffer. When a sentence boundary (`.`, `!`, or `?` followed by whitespace) is detected the sentence is pushed to the TTS queue and synthesised automatically. No response is sent.

### `flush` — drain the buffer

```json
{"pid": 12345, "cmd": "flush"}
```

Forces any remaining buffered text to be synthesised immediately, even if no sentence boundary has been detected. Use this at the end of a generation to ensure the final fragment is spoken. No response is sent.

## Typical usage pattern

1. Subscribe.
2. Send a stream of `text` commands as tokens arrive (e.g. from an LLM).
3. Send `flush` after the last token to drain the buffer.
4. Send `unsubscribe` when done.

Audio plays through the system default output device in real time; there is no audio data returned over the pipe.
