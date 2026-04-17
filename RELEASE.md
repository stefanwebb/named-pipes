## New features

- **`ping` command** — built-in health check on every `ToolNamedPipe` server; responds with `"pong"`
- **`status` command** — built-in state query; responds with the server's current `ToolState` value (e.g. `"running"`)
- **`ToolState` enum** — `ToolNamedPipe` now tracks its lifecycle state via a `_state` field; base state is `RUNNING`

## Improvements

- `cpipe --list`, `--pid`, `--clear` now filter to `tool-*` pipes only, ignoring unrelated FIFOs under `/tmp`
- `cpipe --pid` prints a progress message before the slow process scan
- `ToolNamedPipe` loads `SKILL.md` via the concrete subclass's module file (fixes `cpipe chat help` returning wrong content when launched via `cpipe --serve`)
- Restructured chat and TTS servers into subpackages (`named_pipes/chat/`, `named_pipes/tts/`) matching the STT layout
- Removed `BasicPipeChannel` and legacy example scripts; `cpipe` and docs updated to reflect `ToolNamedPipe`-only scope

## Infrastructure / Documentation

- Added `README.md` for chat, STT, and TTS servers covering startup, commands, and `cpipe` examples
- `ping` and `status` documented in protocol spec (`named-pipe-tools.md`), all `SKILL.md` files, and server READMEs
- Fixed CI dependency install (`--no-deps` dropped; now installs via `.[dev]` to include `pydantic`)
