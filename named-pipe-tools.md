# Named Pipe Tools — Protocol Specification

A system for interprocess communication between a locally running **tool** (server) and one or more **clients** (tool users) via named pipes.

## Why Named Pipes?

- **Statefulness**: The tool runs as a persistent process with in-memory state, unlike a CLI that must reload state from disk or an API on every invocation.
- **Low latency**: Named pipes are the fastest IPC mechanism after shared memory — critical for real-time applications like voice agents.

**Example tools**: LLM inference server, STT/TTS streaming server, in-memory key-value store, vector database, browser automation server.

---

## Pipe Layout

Each tool exposes two named pipes:

| Pipe | Path | Writer(s) | Reader |
|------|------|-----------|--------|
| **Upstream** | `/tmp/tool-{name}` | One or more clients | The tool (single reader) |
| **Downstream** (per client) | `/tmp/tool-{name}-{pid}` | The tool | A single client |

> **Naming constraint**: A tool's human-readable name must not end with `-{integer}`, as that suffix is reserved for downstream pipe identification.

### Lifecycle

| Resource | Created by | Deleted by |
|----------|-----------|------------|
| Upstream pipe | Tool | Tool (on exit) |
| Downstream pipe (`-{pid}`) | Client | Client (on disconnect) |

### Subscription Flow

1. Client creates its downstream pipe at `/tmp/tool-{name}-{pid}`.
2. Client sends a `subscribe` message to the upstream pipe.
3. Tool opens the downstream pipe and confirms with `{ "result": "subscribed" }` sent **only to the subscribing client**.
4. Subsequent responses are routed to the **sender's** downstream pipe only, not broadcast to all subscribers.

---

## Message Protocol

All messages are **JSON objects**, one per write.

### Rule

For every message received **except `unsubscribe`**, the tool must write a response to the **sender's** downstream pipe only (identified by the `pid` field). The sole exception is the `exit` response: the tool broadcasts `{ "result": "exiting" }` to **all** subscribed clients before shutting down.

### Required Commands

Every tool must handle these commands. The `pid` field identifies the calling client.

#### `subscribe`
```json
// Request
{ "pid": 1234, "cmd": "subscribe" }

// Response (to subscribing client only)
{ "result": "subscribed" }
```
Opens the client's downstream pipe.

#### `unsubscribe`
```json
// Request
{ "pid": 1234, "cmd": "unsubscribe" }

// No response (downstream pipe is now closed)
```
Closes the client's downstream pipe.

#### `ping`
```json
// Request
{ "pid": 1234, "cmd": "ping" }

// Response (to sender only)
{ "result": "pong" }
```
Health check. Confirms the tool is alive and processing messages.

#### `description`
```json
// Request
{ "pid": 1234, "cmd": "description" }

// Response (to sender only)
{ "result": "Natural language description of when to use this tool" }
```

#### `help`
```json
// Request
{ "pid": 1234, "cmd": "help" }

// Response (to sender only)
{ "result": "<content of SKILL.md>" }
```

#### `exit`
```json
// Request
{ "pid": 1234, "cmd": "exit" }

// Response (broadcast to ALL subscribers, then tool shuts down)
{ "result": "exiting" }

// Response (if rejected, to sender only)
{ "result": "rejected" }
```
If the tool honors the request, it broadcasts `{ "result": "exiting" }` to **all** subscribed clients before shutting down.

### Custom Commands

Tools may define additional commands. The only constraint is that all messages must be valid JSON, and responses must be sent only to the requesting client (via its `pid`).

---

## Binary Data Protocol

When binary data is sent upstream (client → tool), the frame format is:

```
[4-byte PID big-endian][4-byte length big-endian][payload]
```

When the tool sends binary data downstream to a specific client, the frame format is:

```
[4-byte length big-endian][payload]
```

The downstream direction needs no PID because each client has its own dedicated downstream pipe.

---

## Future Work

- **Browser integration**: Determine whether and how a browser could interact with a named pipe tool.
