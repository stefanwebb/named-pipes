# chat — LLM chat inference server

Serves streaming and blocking LLM chat inference over a named pipe using **Qwen3.5-0.8B** (HuggingFace Transformers backend by default).

Pipe: `/tmp/tool-chat`

## Starting the server

```bash
conda activate named-pipes
cpipe --serve chat
```

The server loads the model on startup (this takes a few seconds), then prints:

```
CHAT server listening on /tmp/tool-chat ...
```

## Commands

### Built-in (all ToolNamedPipe servers support these)

| Command | Description |
|---|---|
| `ping` | Health check — responds with `pong` |
| `status` | Current server state (e.g. `running`) |
| `description` | One-line description of the server |
| `help` | Full help text (this file) |
| `stop` | Shut the server down gracefully |

### Chat commands

#### `chat` — streaming inference

Sends tokens back as they are generated.

```bash
cpipe chat chat -j '{"messages": [{"role": "user", "content": "Hello"}]}'
```

The server replies with one chunk per token batch, followed by a done sentinel:

```json
{"result": "<token>", "done": false}
{"result": "", "done": true}
```

#### `chat_blocking` — non-streaming inference

Waits for the full response before replying.

```bash
cpipe chat chat_blocking -j '{"messages": [{"role": "user", "content": "Hello"}]}'
```

Replies with a single message:

```json
{"result": "<full reply text>"}
```

## Message format

The `messages` array follows the OpenAI chat format:

```json
[
  {"role": "system", "content": "You are a helpful assistant."},
  {"role": "user", "content": "What is 2 + 2?"},
  {"role": "assistant", "content": "4"},
  {"role": "user", "content": "And 3 + 3?"}
]
```

## States

The server broadcasts `{"event": "state_changed", "state": "<value>"}` to all subscribers on every transition. The `status` command returns the current state.

| State | When |
|-------|------|
| `running` | Server process started |
| `loading` | Model weights are being loaded |
| `idle` | Model loaded; no inference in progress |
| `inferring` | Generating tokens (streaming or blocking) |
| `stopping` | `stop` command received; shutting down |
| `error` | Unrecoverable error during load or inference |

## Examples

```bash
# Check the server is running
cpipe --list

# Get a one-line description
cpipe chat description

# Streaming chat
cpipe chat chat -j '{"messages": [{"role": "user", "content": "Tell me a joke"}]}'

# Blocking chat
cpipe chat chat_blocking -j '{"messages": [{"role": "user", "content": "What is the capital of France?"}]}'

# Multi-turn conversation
cpipe chat chat -j '{"messages": [{"role": "user", "content": "My name is Alice"}, {"role": "assistant", "content": "Nice to meet you, Alice!"}, {"role": "user", "content": "What is my name?"}]}'

# Shut down the server
cpipe chat stop
```
