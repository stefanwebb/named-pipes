# Sender-Targeted Routing Design

**Date:** 2026-04-05
**Status:** Approved

## Summary

Change the named-pipe tool protocol so that responses are routed only to the client that sent the triggering command, rather than broadcast to all subscribers. A separate `broadcast_message` / `broadcast_data` method is retained for server-initiated notifications (e.g. graceful shutdown).

---

## Motivation

Broadcasting every response to all subscribers couples unrelated clients and leaks one client's results to another. Targeted routing makes each client's view private by default, with opt-in broadcasting for genuine fan-out events.

---

## TextNamedPipe

### Listener loop

The listener extracts `pid` from the incoming JSON and passes it explicitly to `msg_handler_fn`:

```python
pid = msg.get("pid")
self.msg_handler_fn(msg, pid)
```

### Abstract method signature

```python
@abstractmethod
def msg_handler_fn(self, msg: dict, pid: int | None): ...
```

`pid` is `None` on the client side (server responses carry no pid field).

### send_message / broadcast_message

```python
def send_message(self, data: str, pid: int | None = None):
    """Send to one subscriber (pid given) or all subscribers (pid=None)."""

def broadcast_message(self, data: str):
    """Convenience alias: send to all subscribers."""
    self.send_message(data, pid=None)
```

On the client side, `send_message` is unchanged (writes upstream).

---

## DataNamedPipe

### Wire protocol

| Direction | Frame format |
|-----------|-------------|
| Client → Server (upstream) | `[4-byte PID big-endian][4-byte length big-endian][payload]` |
| Server → Client (downstream) | `[4-byte length big-endian][payload]` (unchanged) |

The downstream direction needs no PID because the server already targets a specific client's pipe.

### API changes

```python
# CLIENT: prepends own PID automatically
def send_data(self, data: bytes): ...

# SERVER: returns (pid, bytes); CLIENT: returns (None, bytes)
def recv_data(self) -> tuple[int | None, bytes]: ...

# Abstract method gains pid
@abstractmethod
def data_handler_fn(self, data: bytes, pid: int | None): ...

# SERVER: send to one subscriber
def send_data(self, data: bytes, pid: int): ...

# SERVER: send to all subscribers
def broadcast_data(self, data: bytes): ...
```

The listener loop passes the extracted pid to `data_handler_fn`.

---

## ToolNamedPipe

### send_response

```python
def send_response(self, result: str, pid: int | None = None):
    self.send_message(json.dumps({"result": result}), pid)
```

### msg_handler_fn

All built-in command handlers receive `pid` and forward it to `send_response`:

| Command | Routing |
|---------|---------|
| `subscribe` | `send_response("subscribed", pid)` — subscribing client only |
| `unsubscribe` | No response |
| `description` | `send_response(..., pid)` — sender only |
| `help` | `send_response(..., pid)` — sender only |
| `exit` | `broadcast_message(...)` — all subscribers, then stop |

### Custom handler signature

Functions registered via `@tool.handler("CMD")` change from `fn(msg)` to `fn(msg, pid)`.

### _dispatch

```python
def _dispatch(self, cmd: str, msg: dict, pid: int | None):
    fn = self._handlers.get(cmd)
    if fn:
        fn(msg, pid)
    else:
        self.send_response(f"unknown command '{cmd}'", pid)
```

---

## ChatNamedPipe

The `on_chat` handler gains `pid` and forwards it to `send_response`:

```python
@self.handler("chat")
def on_chat(msg: dict, pid: int | None):
    messages = msg.get("messages", [])
    reply = self._infer(messages)
    self.send_response(reply, pid)
```

---

## Example code (ex_chat_pipe)

**client.py** — no changes required. The client's `msg_handler_fn` receives `pid=None` and never calls `send_response`.

**server.py** — no changes required (changes are inside `ChatNamedPipe`).

---

## named-pipe-tools.md protocol changes

1. **Subscription flow step 3**: confirmation sent only to the subscribing client, not all subscribers.
2. **Message rule**: responses go to the sender's downstream pipe only. The `exit` response is the sole exception — it broadcasts to all subscribers before shutdown.
3. **`subscribe` response comment** updated to say "to subscribing client only".

---

## What is NOT changing

- Pipe layout and paths (`/tmp/tool-{name}`, `/tmp/tool-{name}-{pid}`)
- Client-side text wire format
- Downstream (server→client) data wire format
- Subscribe/unsubscribe lifecycle
- `send_command` (client only, no pid routing involved)
