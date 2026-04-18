# chat — LLM chat inference over a named pipe

Serves streaming and blocking LLM chat inference using **Qwen3.5-0.8B** (HuggingFace Transformers backend).

Pipe: `/tmp/tool-chat`

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

## Chat commands

### `chat` — streaming inference

```json
{"pid": 12345, "cmd": "chat", "messages": [{"role": "user", "content": "Hello"}]}
```

The server replies with one or more chunk messages followed by a done sentinel:

```json
{"result": "<token chunk>", "done": false}
{"result": "", "done": true}
```

### `chat_blocking` — non-streaming inference

```json
{"pid": 12345, "cmd": "chat_blocking", "messages": [{"role": "user", "content": "Hello"}]}
```

Replies with a single message when generation is complete:

```json
{"result": "<full reply text>"}
```

## Message format

All messages are newline-delimited JSON sent over the named pipe. Each client must subscribe before sending chat commands. The `messages` array follows the OpenAI chat format: each entry is `{"role": "user"|"assistant"|"system", "content": "..."}`.
