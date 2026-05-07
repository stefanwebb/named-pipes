# named_pipes.pipes

Low-level named-pipe (FIFO) transport layer. Provides binary and text abstractions that handle pipe creation, non-blocking I/O, background listener threads, and the subscription model used by the higher-level tool protocol.

## Classes

### `Role`

```python
class Role(Enum):
    SERVER = "server"
    CLIENT = "client"
```

Distinguishes the two ends of a pipe pair. Servers own the upstream FIFO; clients own their per-PID downstream FIFO.

---

### `DataNamedPipe`

Binary streaming pipe with a structured wire format.

**Wire format**

| Direction | Header | Payload |
|---|---|---|
| upstream (client → server) | `[4-byte PID][4-byte length]` | raw bytes |
| downstream (server → client) | `[4-byte length]` | raw bytes |

**Subscription model**

A single upstream FIFO is shared by all clients. When a client sends a message the server reads the 4-byte PID prefix and routes the reply to that client's downstream FIFO (`/tmp/tool-{name}-{pid}`).

**Context manager**

```python
with DataNamedPipe("/tmp/tool-demo", Role.SERVER) as pipe:
    ...
```

Opens the FIFOs, starts the background listener thread, and closes/joins on exit.

**Key methods**

| Method | Description |
|---|---|
| `send(data, pid=None)` | Write bytes to the pipe; `pid` routes server-to-client |
| `start_listening()` | Spawn the background `select`-based reader thread |
| `stop()` | Signal the listener thread to exit |

---

### `TextNamedPipe`

JSON message pipe built on top of `DataNamedPipe`.

Messages are newline-delimited JSON objects. The listener thread deserialises each line and dispatches it to registered handlers.

**Handler registration**

```python
pipe.on("event_name", handler_fn)
```

Handlers receive the full parsed `dict`. Multiple handlers per event name are supported.

**Key methods**

| Method | Description |
|---|---|
| `send_message(msg, pid=None)` | Serialise `msg` to JSON and write to the pipe |
| `broadcast(msg)` | Send `msg` to every subscribed client |
| `on(event, fn)` | Register a handler for a named event |

## Implementation Notes

- Both classes use `select.select()` for non-blocking reads so the listener thread never hard-blocks on an empty pipe.
- All FIFOs are opened with `O_RDWR` (read-write), which prevents `open()` from blocking waiting for the other end and means the read end never receives a spurious EOF when the writer closes briefly.
- A message-draining step flushes leftover kernel-buffered bytes when the listener restarts, preventing stale data from being delivered to new subscribers.
