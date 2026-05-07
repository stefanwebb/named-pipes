# named_pipes.chat

LLM chat inference server over named pipes. Accepts conversation messages from connected clients and streams or returns model-generated replies.

Pipe: `/tmp/tool-chat`

## Classes

### `ChatServer`

`ToolServer` subclass. Implements the `CHAT` interface on top of the base `ToolServer` commands.

**Supported commands**

| Command | Description |
|---|---|
| `chat` | Streaming inference — emits `token` events per token batch, then a `token` with `done: true` |
| `chat_blocking` | Synchronous inference — emits a single `reply` event |

The server enforces a state machine so only one inference runs at a time:

```
LOADING → IDLE → INFERRING → IDLE
                           → ERROR
```

Streaming inference runs in a dedicated thread to avoid blocking the listener loop.

---

### `ChatConfig`

Pydantic model holding server configuration.

| Field | Type | Default | Description |
|---|---|---|---|
| `model` | `str` | — | Model name or HuggingFace path |
| `backend` | `Backend` | `TRANSFORMERS` | Inference backend |
| `max_new_tokens` | `int` | `512` | Generation token limit |
| `temperature` | `float` | `1.0` | Sampling temperature |
| `verbose` | `bool` | `False` | Log inference events to stdout |

Additional kwargs are forwarded directly to the backend's generation call.

---

### `Backend`

```python
class Backend(Enum):
    TRANSFORMERS = "transformers"
    VLLM         = "vllm"
    VLLM_MLX     = "vllm_mlx"
    MLX_LM       = "mlx_lm"
```

Backend imports are deferred so unused backends don't need to be installed.

---

### `ChatState`

```python
class ChatState(Enum):
    LOADING    = "loading"
    IDLE       = "idle"
    INFERRING  = "inferring"
    ERROR      = "error"
```

## Backend Behaviour

### `TRANSFORMERS`

Uses `transformers.TextIteratorStreamer` in a separate thread — token events arrive incrementally without blocking the listener loop.

### `VLLM` / `VLLM_MLX`

Calls the vLLM engine and forwards `SamplingParams`. Returns the full response as a single `token` event followed by `done` (no per-token streaming).

### `MLX_LM`

Uses `mlx_lm.generate` with streaming on Apple Silicon.

## Launching

### From Python

```python
from named_pipes.chat import ChatServer, ChatConfig, Backend

config = ChatConfig(model="Qwen/Qwen2.5-0.5B-Instruct", backend=Backend.TRANSFORMERS)
server = ChatServer(config)
server.start()  # blocks until stop
```

### From the CLI

```bash
cpipe --serve chat
```

### Via `launch.py`

`named_pipes.chat.launch` is the subprocess entry point used by the TUI. It reads a JSON-serialised `ChatConfig` from `argv[1]`.

## Wire Example

```
→ {"pid": 1234, "cmd": "chat", "messages": [{"role": "user", "content": "Hello!"}]}
← {"event": "token", "text": "Hello", "done": false}
← {"event": "token", "text": "!  How can I help?", "done": false}
← {"event": "token", "text": "", "done": true}
```

The `messages` array follows the OpenAI chat format (`role` + `content` pairs).
