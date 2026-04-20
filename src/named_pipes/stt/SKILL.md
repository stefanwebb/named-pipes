# stt — real-time speech-to-text over a named pipe

Captures audio from the default microphone and broadcasts transcribed tokens in real time, using **Voxtral Mini 4B Realtime** (vendored MLX implementation under `named_pipes.stt.voxtral`). Speech onset and end are detected with Silero VAD; subscribers see an utterance-bracketed stream of token messages.

Pipe: `/tmp/tool-stt`

## Built-in commands

| Command | Request | Response event |
|---|---|---|
| `subscribe` | `{"pid": <int>, "cmd": "subscribe"}` | `{"event": "subscribed"}` |
| `unsubscribe` | `{"pid": <int>, "cmd": "unsubscribe"}` | *(none)* |
| `ping` | `{"pid": <int>, "cmd": "ping"}` | `{"event": "pong"}` |
| `get_state` | `{"pid": <int>, "cmd": "get_state"}` | `{"event": "state", "state": "<value>"}` e.g. `"running"` |
| `get_description` | `{"pid": <int>, "cmd": "get_description"}` | `{"event": "description", "description": "<one-line description>"}` |
| `get_help` | `{"pid": <int>, "cmd": "get_help"}` | `{"event": "help", "help": "<this text>"}` |
| `get_config` | `{"pid": <int>, "cmd": "get_config"}` | `{"event": "config", ...}` |
| `stop` | `{"pid": <int>, "cmd": "stop"}` | `{"event": "state_changed", "state": "stopping"}` broadcast to all subscribers, then server exits |

## Broadcasts

The tool is producer-only; it has no custom request commands. While subscribed, a client receives the following events in order for each utterance:

| When | Event |
|---|---|
| VAD detects start of speech | `{"event": "speech_start"}` |
| Per token emitted by the decoder | `{"event": "token", "text": "<token>"}` |
| All tokens for the utterance have been emitted and VAD has detected end of speech | `{"event": "speech_end"}` |

Tokens are sub-word pieces as produced by the Voxtral tokenizer — subscribers that want whole words should concatenate consecutive `token` texts until the next `speech_end`.

## Typical usage pattern

1. Start the server (`cpipe --serve stt`) — model load takes several seconds.
2. Subscribe.
3. Speak into the system default microphone.
4. Receive a stream of `speech_start` / `token` / `speech_end` events per utterance.
5. Send `unsubscribe` when done; send `stop` to shut the server down cleanly.

Audio capture uses the system default input device; there is no audio returned over the pipe, only text.
