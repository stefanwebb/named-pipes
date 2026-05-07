# named_pipes.tools

Named Pipe Tools protocol layer. Implements the command/event handshake on top of `TextNamedPipe`, providing `ToolServer` and `ToolClient` as the primary building blocks for any named-pipe service.

## Protocol Summary

```
Client → Server  {"pid": <int>, "cmd": "<name>", ...args}
Server → Client  {"event": "<name>", ...fields}
```

A client first sends `subscribe` to register its downstream FIFO, then sends arbitrary commands. The server routes replies to the correct downstream FIFO using the `pid` field.

## Classes

### `ToolServer`

Listens on `/tmp/tool-{name}`, dispatches incoming commands to handlers, and broadcasts events to subscribers.

**Built-in commands** (handled automatically)

| Command | Description |
|---|---|
| `subscribe` | Register a client's downstream FIFO |
| `unsubscribe` | Deregister a client |
| `ping` | Reply with a `pong` event |
| `get_state` | Reply with current server state string |
| `get_description` | Reply with the server's human-readable description |
| `get_help` | Reply with help text loaded from `HELP.md` |
| `get_config` | Reply with the serialised config object |
| `get_interface` | Reply with a named interface definition |
| `list_interfaces` | Reply with all registered interface names |
| `stop` | Initiate graceful shutdown |

**Custom command handlers**

```python
server = ToolServer("myservice")

@server.handler("greet")
def handle_greet(pid, cmd, name="world"):
    server.send_event({"event": "greeting", "message": f"Hello, {name}!"}, pid=pid)
```

**Key methods**

| Method | Description |
|---|---|
| `handler(cmd)` | Decorator to register a custom command handler |
| `send_event(msg, pid=None)` | Send an event to one client (`pid`) or broadcast to all |
| `broadcast(msg)` | Send an event to every subscriber |
| `start()` / `stop()` | Lifecycle management |
| `register_interface(iface)` | Add an `Interface` definition for introspection |

**State machine**

`ToolState.RUNNING` → `ToolState.STOPPING`

---

### `ToolClient`

Connects to a named server, creates a per-PID downstream FIFO, subscribes, and delivers events to registered handlers.

```python
with ToolClient("myservice") as client:
    client.on("greeting", lambda msg: print(msg["message"]))
    client.send_command({"cmd": "greet", "name": "Alice"})
```

**Key methods**

| Method | Description |
|---|---|
| `on(event, fn)` | Register a handler for a named event |
| `send_command(msg)` | Send a command dict to the server |
| `subscribe()` | Send the `subscribe` handshake (called automatically by context manager) |
| `start_listening()` | Start the background listener thread |

---

### `ToolState`

```python
class ToolState(Enum):
    RUNNING  = "running"
    STOPPING = "stopping"
```

## Usage Pattern

```python
# Server process
server = ToolServer("demo")

@server.handler("echo")
def echo(pid, cmd, message=""):
    server.send_event({"event": "echo", "message": message}, pid=pid)

server.start()  # blocks until stop() is called

# Client process
with ToolClient("demo") as client:
    replies = []
    client.on("echo", lambda m: replies.append(m["message"]))
    client.send_command({"cmd": "echo", "message": "hello"})
```
