# named_pipes.interfaces

Protocol schema system. Defines the commands and events exposed by each service as structured `Interface` objects with typed argument/field specifications. These definitions drive introspection (`get_interface`, `list_interfaces`) and are surfaced in the TUI and CLI.

## Classes

### `Interface`

A named collection of command and event specs.

```python
@dataclass
class Interface:
    name: str
    commands: list[CommandSpec]
    events: list[EventSpec]
```

### `CommandSpec`

Describes a single command that a server accepts.

```python
@dataclass
class CommandSpec:
    name: str
    args: list[ArgSpec]
    description: str = ""
```

### `EventSpec`

Describes a single event that a server emits.

```python
@dataclass
class EventSpec:
    name: str
    fields: list[ArgSpec]
    description: str = ""
```

### `ArgSpec`

Metadata for one command argument or event field.

```python
@dataclass
class ArgSpec:
    name: str
    type: str           # e.g. "str", "int", "float", "bool"
    required: bool = True
    default: Any = None
    description: str = ""
```

## Predefined Interfaces

### `BASE`

Built-in commands present on every `ToolServer`. Clients can always rely on these without knowing the service type.

| Command | Description |
|---|---|
| `ping` | Liveness check; server replies with `pong` |
| `get_description` | Returns the server's human-readable description |
| `get_help` | Returns help text from `HELP.md` |
| `get_config` | Returns the serialised configuration object |
| `get_state` | Returns current state enum value |
| `get_interface` | Returns a named interface definition |
| `list_interfaces` | Returns all registered interface names |
| `stop` | Graceful shutdown |

---

### `CHAT`

LLM chat inference interface (`named_pipes.chat`).

**Commands**

| Command | Args | Description |
|---|---|---|
| `chat` | `messages: list` | Streaming inference; emits `chunk` events then `done` |
| `chat_blocking` | `messages: list` | Synchronous inference; emits single `reply` event |

**Events**

| Event | Fields | Description |
|---|---|---|
| `chunk` | `text: str` | One streamed token or token group |
| `done` | — | Streaming complete |
| `reply` | `text: str` | Full response (blocking mode) |

---

### `TTS`

Text-to-speech interface (`named_pipes.tts`).

**Commands**

| Command | Args | Description |
|---|---|---|
| `text` | `text: str` | Append text to the synthesis queue |
| `flush` | — | Force synthesis of any buffered text |
| `is_speaking` | — | Query whether audio is currently playing |

**Events**

| Event | Fields | Description |
|---|---|---|
| `is_speaking` | `value: bool` | Response to the `is_speaking` command |
| `speech_start` | — | Audio playback has begun |
| `speech_end` | — | Audio playback has ended |

---

### `STT`

Speech-to-text interface (`named_pipes.stt`). Producer-only — no custom commands; the server broadcasts events continuously.

**Events**

| Event | Fields | Description |
|---|---|---|
| `token` | `text: str` | Transcribed text fragment |
| `speech_start` | — | VAD detected speech onset |
| `speech_end` | — | VAD detected speech offset |
