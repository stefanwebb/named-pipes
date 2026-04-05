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
3. Tool opens the downstream pipe and confirms with `{ "result": "subscribed" }`.
4. Tool writes to all subscribed downstream pipes on every response.

---

## Message Protocol

All messages are **JSON objects**, one per write.

### Rule

For every message received **except `unsubscribe`**, the tool must write a response to all subscribed downstream pipes — even if the response is just an empty acknowledgment.

### Required Commands

Every tool must handle these commands. The `pid` field identifies the calling client.

#### `subscribe`
```json
// Request
{ "pid": 1234, "cmd": "subscribe" }

// Response (to all subscribers)
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

#### `description`
```json
// Request
{ "pid": 1234, "cmd": "description" }

// Response
{ "result": "Natural language description of when to use this tool" }
```

#### `help`
```json
// Request
{ "pid": 1234, "cmd": "help" }

// Response
{ "result": "<content of SKILL.md>" }
```

#### `exit`
```json
// Request
{ "pid": 1234, "cmd": "exit" }

// Response (if honored)
{ "result": "exiting" }

// Response (if rejected)
{ "result": "rejected" }
```
If the tool honors the request, it broadcasts `{ "result": "exiting" }` to all subscribed clients before shutting down.

### Custom Commands

Tools may define additional commands. The only constraint is that all messages must be valid JSON.

---

## Future Work

- **Binary data support**: Extend the protocol to handle raw binary payloads (images, audio).
- **Browser integration**: Determine whether and how a browser could interact with a named pipe tool.
