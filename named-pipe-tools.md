# Named Pipe Tools — Protocol Specification

A system for interprocess communication between a locally running **tool server** (`ToolServer`) and one or more **clients** (`ToolClient`) via named pipes.

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
| Upstream pipe | Tool | Tool (on stop) |
| Downstream pipe (`-{pid}`) | Client | Client (on disconnect) |

### Subscription Flow

1. Client creates its downstream pipe at `/tmp/tool-{name}-{pid}`.
2. Client sends a `subscribe` message to the upstream pipe.
3. Tool opens the downstream pipe and responds with a `subscribed` event sent **only to the subscribing client**.
4. Subsequent responses are routed to the **sender's** downstream pipe only, not broadcast to all subscribers.

---

## Message Protocol

All messages are **JSON objects**, one per write.

### Message Shapes

**Client → Server (commands)**
```json
{ "pid": 1234, "cmd": "<command name>", "<key>": "<value>", "...": "..." }
```
The `pid` field identifies the calling client. Additional key-value pairs are command-specific.

**Server → Client (events)**
```json
{ "event": "<event name>", "<key>": "<value>", "...": "..." }
```
Additional key-value pairs are event-specific.

### Routing Rule

For every command received **except `unsubscribe`**, the tool must send a response event to the **sender's** downstream pipe only (identified by the `pid` field). The sole exception is `state_changed`: the tool broadcasts that event to **all** subscribed clients whenever the tool's state changes.

### Required Commands

Every tool must handle these commands.

#### `subscribe`
```json
// Command
{ "pid": 1234, "cmd": "subscribe" }

// Event (to subscribing client only)
{ "event": "subscribed" }
```
Opens the client's downstream pipe.

#### `unsubscribe`
```json
// Command
{ "pid": 1234, "cmd": "unsubscribe" }

// No event (downstream pipe is now closed)
```
Closes the client's downstream pipe.

#### `ping`
```json
// Command
{ "pid": 1234, "cmd": "ping" }

// Event (to sender only)
{ "event": "pong" }
```
Health check. Confirms the tool is alive and processing messages.

#### `get_state`
```json
// Command
{ "pid": 1234, "cmd": "get_state" }

// Event (to sender only)
{ "event": "state", "state": "<value>" }
```
Returns the tool's current state (e.g. `"running"`). Subclasses may define additional states beyond the base set.

#### `get_description`
```json
// Command
{ "pid": 1234, "cmd": "get_description" }

// Event (to sender only)
{ "event": "description", "description": "Natural language description of when to use this tool" }
```

#### `get_help`
```json
// Command
{ "pid": 1234, "cmd": "get_help" }

// Event (to sender only)
{ "event": "help", "help": "<content of SKILL.md>" }
```

#### `get_config`
```json
// Command
{ "pid": 1234, "cmd": "get_config" }

// Event (to sender only)
{ "event": "config", "<key>": "<value>", "...": "..." }
```
Returns the tool's current configuration as key-value pairs.

#### `stop`
```json
// Command
{ "pid": 1234, "cmd": "stop" }

// No direct response — tool changes state, which broadcasts state_changed to all subscribers
```
The tool transitions to the `stopping` state, which triggers a `state_changed` broadcast to all subscribed clients, then shuts down.

### Error (unknown or invalid command)

If the tool receives a command it does not recognise, it sends an error event to the requesting client:

```json
// Event (to sender only)
{ "event": "error", "message": "unknown command '<cmd>'" }
```

---

## Tool State

Every tool tracks a current state and broadcasts a `state_changed` event to all subscribers whenever it changes.

### `state_changed` event

```json
{ "event": "state_changed", "state": "<value>" }
```

Broadcast to **all** subscribers whenever the tool's state changes. Clients can use this to track the tool's lifecycle without polling `get_state`.

### Base states

All tools expose at minimum:

| State | When |
|-------|------|
| `running` | Tool is initialised and ready to handle commands |
| `stopping` | Tool has received `stop` and is shutting down |

### Extended states

Subclasses may define additional states. These are returned by `get_state` and included in `state_changed` broadcasts.

| Tool | Additional states | Meaning |
|------|-------------------|---------|
| **chat** | `loading` | Model is being loaded |
| | `idle` | Model loaded; no inference in progress |
| | `inferring` | Generating tokens |
| | `error` | Unrecoverable error during load or inference |
| **stt** | `loading` | ASR and VAD models are being loaded |
| | `listening` | Models loaded; waiting for speech |
| | `transcribing` | Speech detected; decoding tokens |
| | `error` | Unrecoverable error |
| **tts** | `loading` | TTS model is being loaded |
| | `idle` | Model loaded; sentence queue empty |
| | `synthesizing` | Generating audio for a sentence |
| | `error` | Unrecoverable error during load |

---

## Custom Commands and Events

Tools may define additional commands and events. The only constraints are:

- All commands must match the shape `{ "pid": <int>, "cmd": "<name>", ... }`.
- All events must match the shape `{ "event": "<name>", ... }`.
- Responses must be sent only to the requesting client (via its `pid`), except for broadcast events like `state_changed`.

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
