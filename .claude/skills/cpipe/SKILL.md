---
name: cpipe
description: Use cpipe to discover, inspect, and send commands to named-pipe tool servers.
allowed-tools: [Bash]
---

Use `cpipe` to interact with named-pipe tool servers. Always activate the `named-pipes` conda environment first.

```bash
conda activate named-pipes
```

## Discover running servers

```bash
cpipe --list          # list all named pipes under /tmp (fast, no process scan)
cpipe --pid           # same, but also show which PIDs have each pipe open
cpipe --clear         # delete orphaned pipes (no live process) under /tmp
```

Pass an optional directory to search a different root (e.g. `cpipe --list /var/tmp`).

## Send commands to a tool server

```bash
cpipe <tool> <cmd>
```

`<tool>` is either a bare tool name (e.g. `chat`) — which resolves to `/tmp/tool-chat` — or a full pipe path. `<cmd>` is the command to send.

### Built-in commands every tool supports

```bash
cpipe chat description          # one-line description of the tool
cpipe chat help                 # full help text (SKILL.md content)
cpipe chat exit                 # shut the server down gracefully
```

### Sending data

```bash
cpipe chat greet -d Alice                        # -d / --data sets the "data" field
cpipe chat greet Alice                           # positional DATA works too
cpipe chat chat -j '{"messages":[{"role":"user","content":"Hello"}]}'  # merge extra JSON fields
```

### Streaming responses

`cpipe` detects streaming automatically. Chunks are printed as they arrive; the command exits after the final `{"done": true}` sentinel.

```bash
cpipe chat chat -j '{"messages":[{"role":"user","content":"Tell me a joke"}]}'
```

## Protocol flags

| Flag | Effect |
|---|---|
| `--tool` | Force tool protocol (`subscribe`/`unsubscribe` handshake) |
| `--basic` | Force basic pipe protocol (`SUBSCRIBE`/`SUBSCRIBED` handshake) |
| `--no-subscribe` | Skip the subscribe/unsubscribe handshake entirely |
| `-n` / `--no-wait` | Fire-and-forget; do not wait for a response |
| `-t SECS` / `--timeout SECS` | Response timeout in seconds (default: 5.0) |
| `-v` / `--verbose` | Print sent messages and status to stderr |

Bare tool names and `/tmp/tool-*` paths default to tool protocol. Any other absolute path defaults to basic protocol.

## Basic-protocol servers

```bash
cpipe /tmp/basic_pipe PING --basic
cpipe /tmp/basic_pipe GREET -d Bob --basic
```

## Examples

```bash
cpipe --list                                         # what's running?
cpipe chat description                               # what does this tool do?
cpipe chat help                                      # full API reference
cpipe tts text -d "Hello, world"                     # send a text chunk to the TTS server
cpipe tts flush                                      # drain the TTS buffer
cpipe chat exit                                      # shut down the LLM server
cpipe --clear                                        # clean up stale pipes after a crash
```
