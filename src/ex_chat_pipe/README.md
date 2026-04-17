# ex_chat_pipe

Example: LLM chat inference served over a named pipe.

The server loads **Qwen3.5-0.8B** via HuggingFace Transformers and handles
`chat` commands from any number of subscribers. The client connects, sends a
single question, and prints the reply.

## Files

| File | Role |
|---|---|
| `client.py` | `TextNamedPipe` client — subscribes, sends one query, prints the response |

## Running

Start the server first (it creates the FIFO and loads the model):

```bash
conda activate named-pipes
cpipe --serve chat
```

Then, in a separate terminal, run the client:

```bash
conda activate named-pipes
python src/ex_chat_pipe/client.py
```

Expected output from the client:

```
Sending: What is the capital of France?
Response: Paris
```

## Named pipes

| Path | Direction | Purpose |
|---|---|---|
| `/tmp/tool-llm` | client → server | Shared upstream; all clients write here |
| `/tmp/tool-llm-<pid>` | server → client | Per-subscriber downstream; created by the client on connect |

## Protocol

All messages are newline-delimited JSON.

**Subscribe**

```json
// client → server
{"pid": 12345, "cmd": "subscribe"}

// server → client
{"result": "subscribed"}
```

**Chat**

```json
// client → server
{"pid": 12345, "cmd": "chat", "messages": [{"role": "user", "content": "..."}]}

// server → client
{"result": "<assistant reply text>"}
```

## Backend options

`ChatNamedPipe` supports two backends via the `backend` parameter:

| Backend | Default kwargs | Notes |
|---|---|---|
| `Backend.TRANSFORMERS` | `max_new_tokens`, `do_sample`, … | Used in this example |
| `Backend.VLLM` | `temperature`, `max_tokens`, … | Requires vLLM installed |
