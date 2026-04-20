# chat — LLM chat inference over a named pipe

Serves streaming and blocking LLM chat inference using **Qwen3.5-0.8B** (HuggingFace Transformers backend).

Pipe: `/tmp/tool-chat`

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

## Chat commands

### `chat` — streaming inference

```json
{"pid": 12345, "cmd": "chat", "messages": [{"role": "user", "content": "Hello"}]}
```

The server replies with one or more token events followed by a done sentinel:

```json
{"event": "token", "text": "<token chunk>", "done": false}
{"event": "token", "text": "", "done": true}
```

### `chat_blocking` — non-streaming inference

```json
{"pid": 12345, "cmd": "chat_blocking", "messages": [{"role": "user", "content": "Hello"}]}
```

Replies with a single event when generation is complete:

```json
{"event": "reply", "text": "<full reply text>"}
```

## Message format

All messages are newline-delimited JSON sent over the named pipe. Each client must subscribe before sending chat commands. The `messages` array follows the OpenAI chat format: each entry is `{"role": "user"|"assistant"|"system", "content": "..."}`.
