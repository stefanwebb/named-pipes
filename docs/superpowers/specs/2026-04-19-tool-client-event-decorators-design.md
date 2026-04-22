# ToolClient Event Decorator Handlers

**Date:** 2026-04-19

## Summary

Refactor `ToolClient` and all example clients to use `@self.on("event")` decorator handlers, mirroring the existing `@server.handler("cmd")` pattern in `ToolServer`.

## Changes

### `src/named_pipes/tool_client.py`

- Add `self._handlers: dict[str, callable] = {}` in `__init__`
- Add `on(event: str)` decorator method that registers a callable in `_handlers`
- Update `msg_handler_fn`: handle `subscribed` internally first, then dispatch remaining events via `_handlers`; unknown events are silently ignored
- Remove `on_message`

```python
def on(self, event: str):
    def decorator(fn):
        self._handlers[event] = fn
        return fn
    return decorator

def msg_handler_fn(self, msg: dict, pid: int | None):
    if msg.get("event") == "subscribed":
        self._subscribed.set()
        return
    fn = self._handlers.get(msg.get("event", ""))
    if fn:
        fn(msg)
```

### `src/examples/chat_client.py`

- Keep `_LLMClient` subclass; move all event handling from `on_message` into `__init__` using `@self.on("state_changed")`, `@self.on("token")`, `@self.on("reply")`
- `reply_received` and `response` remain as instance attributes, captured by closure

```python
def __init__(self):
    super().__init__("chat")
    self.reply_received = threading.Event()
    self.response: str | None = None

    @self.on("state_changed")
    def _(msg):
        print("on_state_changed", msg.get("state", ""))

    @self.on("token")
    def _(msg):
        if msg.get("done"):
            self.reply_received.set()
        else:
            print(msg.get("text", ""), end="", flush=True)

    @self.on("reply")
    def _(msg):
        self.response = msg.get("text", "")
        self.reply_received.set()
```

### `src/examples/stt_client.py`

- Replace `on_message` override with `@self.on("token")`, `@self.on("speech_start")`, `@self.on("speech_end")` registered in `__init__`

### `src/examples/tts_client.py`

- `_LLMClient`: replace `on_message` with `@self.on("token")` in `__init__`; `on_chunk`/`on_done` callbacks captured by closure
- `_TTSClient`: no `on_message` to convert — no change needed

## Non-Goals

- No change to `ToolServer`, `TextNamedPipe`, or other files
- No support for multiple handlers per event
- No wildcard/catch-all handler
