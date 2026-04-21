## New features

- **`state_changed` handler in `stt_client`** — `_STTClient` now prints server state transitions (`[state_changed] <state>`) as they arrive
- **`speech_start` / `speech_end` events in `TTSServer`** — server broadcasts these events at the boundaries of each synthesis pass; `tts_client` handles them
- **KokoroPipeline warm-up** — `TTSServer` now pre-warms the Kokoro pipeline during `__init__`, reducing first-synthesis latency

## Improvements

- **`@self.on()` decorator in clients** — `stt_client`, `tts_client`, and `chat_client` all migrated from `on_message` callbacks to the `@self.on()` decorator pattern introduced in `ToolClient`
- **`--verbose` flag forwarding** — `cpipe --serve` now correctly passes the `--verbose` flag through to the server config
- **Error event documentation** — protocol spec now documents the `error` event emitted for unknown commands
