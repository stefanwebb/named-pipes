# named_pipes.app

User-facing interfaces for managing and interacting with named-pipe tool servers. Provides a CLI (`cpipe`) and an interactive TUI dashboard.

## CLI — `cpipe`

`cpipe` is a `curl`-like tool for sending commands to named-pipe servers and reading their responses.

### Usage

```bash
cpipe [server] [command] [options]
cpipe --serve {chat,tts,stt}
cpipe --list [root]
cpipe --pid [root]
cpipe --clear [root]
```

### Management flags

| Flag | Description |
|---|---|
| `--serve {chat,tts,stt}` | Launch a server with default config and block |
| `--list [root]` | List all tool pipes under `root` (fast probe) |
| `--pid [root]` | List pipes with owning PIDs (full `psutil` scan) |
| `--clear [root]` | Delete orphaned pipe files |

### Sending commands

```bash
# One-shot command (waits for a reply event, then exits)
cpipe chat ping

# Pass JSON arguments
cpipe chat chat -j '{"messages": [{"role": "user", "content": "Hello"}]}'

# Pass a plain string as a single argument
cpipe tts text -d "Hello, world."

# Fire-and-forget (no reply expected)
cpipe tts text -d "Hello" --no-wait

# Custom timeout
cpipe chat chat -j '{"messages": [...]}' --timeout 30
```

### Protocol detection

`cpipe` probes whether the target is a full Named Pipe Tools server or a bare `TextNamedPipe`. For tool servers it performs the subscribe/unsubscribe handshake automatically. Streaming token events (`done: false` / `done: true`) are printed incrementally.

### `_CpipeClient`

Internal single-shot `ToolClient` subclass. Sends one command, collects responses until a done-flag or timeout, and exits. Not part of the public API.

---

## TUI — `tui.py`

Interactive dashboard built with [Textual](https://textual.textualize.io/). Launch with:

```bash
cpipe --tui
```

### Layout

```
┌─────────────────────────────────┐
│  Tabs: Tools │ Launch │ Info    │
├─────────────────────────────────┤
│  [Tools tab]                    │
│  ┌──────────┐  ┌─────────────┐  │
│  │ Tools    │  │ Output log  │  │
│  │ table    │  │             │  │
│  └──────────┘  └─────────────┘  │
└─────────────────────────────────┘
```

**Tools tab** — live table of discovered tool servers with state, description, and ping latency. Selecting a row opens a detail panel showing events in real time.

**Launch tab** — config builder for starting new chat, TTS, or STT servers as subprocesses.

**Info tab** — system hardware and installed library versions (from `named_pipes.system`).

### `_ManagedClient`

Persistent `ToolClient` that maintains a long-lived connection to a single server. Features:

- Caches description and interface definitions after first fetch
- Polls state and sends periodic pings
- Routes interface-discovery events to the TUI reactively

### `_ToolsTable`

Textual `DataTable` widget listing all discovered servers. Auto-refreshes on pipe discovery events.

### `widgets.py`

| Widget | Description |
|---|---|
| `AutoTextArea` | Self-sizing textarea that resizes to fit its content; pressing Escape blurs focus |
