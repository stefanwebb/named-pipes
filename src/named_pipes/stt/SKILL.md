# stt — real-time speech-to-text over a named pipe

Captures audio from the default microphone and broadcasts transcribed tokens in real time, using **Voxtral Mini 4B Realtime** (vendored MLX implementation under `named_pipes.stt.voxtral`). Speech onset and end are detected with Silero VAD; subscribers see an utterance-bracketed stream of token messages.

Pipe: `/tmp/tool-stt`

## Built-in commands

| Command | Request | Response |
|---|---|---|
| `subscribe` | `{"pid": <int>, "cmd": "subscribe"}` | `{"result": "subscribed"}` |
| `unsubscribe` | `{"pid": <int>, "cmd": "unsubscribe"}` | *(none)* |
| `ping` | `{"pid": <int>, "cmd": "ping"}` | `{"result": "pong"}` |
| `status` | `{"pid": <int>, "cmd": "status"}` | `{"result": "<state>"}` e.g. `"running"` |
| `description` | `{"pid": <int>, "cmd": "description"}` | `{"result": "<one-line description>"}` |
| `help` | `{"pid": <int>, "cmd": "help"}` | `{"result": "<this text>"}` |
| `stop` | `{"pid": <int>, "cmd": "stop"}` | `{"result": "stopping"}` broadcast to all subscribers, then server exits |

## Broadcasts

The tool is producer-only; it has no custom request commands. While subscribed, a client receives the following messages in order for each utterance:

| When | Message |
|---|---|
| VAD detects start of speech | `{"event": "speech_start"}` |
| Per token emitted by the decoder | `{"result": "<token>"}` |
| All tokens for the utterance have been emitted and VAD has detected end of speech | `{"event": "speech_end"}` |

Tokens are sub-word pieces as produced by the Voxtral tokenizer — subscribers that want whole words should concatenate consecutive `result` strings until the next `speech_end`.

## Typical usage pattern

1. Start the server (`cpipe --serve stt`) — model load takes several seconds.
2. Subscribe.
3. Speak into the system default microphone.
4. Receive a stream of `speech_start` / `result` / `speech_end` messages per utterance.
5. Send `unsubscribe` when done; send `stop` to shut the server down cleanly.

Audio capture uses the system default input device; there is no audio returned over the pipe, only text.
