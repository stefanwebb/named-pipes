# Design: serve_llm with TransformersPipeChannel

**Date:** 2026-03-19
**Status:** Approved

## Overview

Add a `TransformersPipeChannel` class that loads a HuggingFace `transformers` model and serves chat inference over the existing named-pipe IPC channel. Update `serve_llm/main.py` to demonstrate the feature using `SmolLM2-135M-Instruct`.

## Goals

- Demonstrate end-to-end LLM inference over named pipes using a very small model
- Mirror the existing `LLMPipeChannel` (vLLM) pattern with a `transformers`-backed sibling
- Keep the implementation simple and readable as a proof-of-concept

## Non-Goals

- Streaming token output
- Concurrent request handling (documented as future work)
- Replacing or modifying `LLMPipeChannel`

## Architecture

### New file: `src/named_pipes/transformers_pipe_channel.py`

Subclasses `BasicPipeChannel`. Constructor signature mirrors `LLMPipeChannel`:
`__init__(self, model: str, pipe_name: str = "/tmp/agent", **generation_kwargs)`

Constructor steps:

1. Calls `super().__init__(pipe_name)`
2. Detects device: `mps` if `torch.backends.mps.is_available()`, else `cuda` if `torch.cuda.is_available()`, else `cpu`
3. Loads `AutoTokenizer.from_pretrained(model)`
4. Loads `AutoModelForCausalLM.from_pretrained(model)` then calls `.to(device)` — **not** `device_map="auto"`, which is unreliable on MPS
5. Stores `generation_kwargs` for use in `model.generate`
6. Registers a `CHAT` handler via `@self.handler("CHAT")`

`CHAT` handler flow:

1. Wrap in `try/except json.JSONDecodeError` → on error, `self.send_message("ERROR", "invalid JSON")` and return
2. `json.loads(data)` → list of `{"role": str, "content": str}` dicts
3. `tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_tensors="pt")` → CPU tensor; call `.to(device)` before passing to model
4. `model.generate(input_ids, **generation_kwargs)` → output tensor. Note: `temperature` requires `do_sample=True` to take effect; callers should pass both together
5. Slice off prompt tokens: `output_ids[0][input_ids.shape[-1]:]`
6. `tokenizer.decode(new_tokens, skip_special_tokens=True)` → reply string
7. `self.send_message("CHAT_RESPONSE", reply)` — calls `BasicPipeChannel.send_message(cmd, data)`, not the base class single-arg version

A comment block after the handler documents the Option B worker-thread pattern:
- A `queue.Queue` holds `(messages, reply_event)` pairs
- A dedicated inference thread owns the model and processes requests serially
- Enables future cancellation and non-blocking listener thread
- Note: with Option A, QUIT handling is also blocked during inference; Option B resolves this

Constructor accepts `**generation_kwargs` forwarded to `model.generate` (e.g. `max_new_tokens=256`, `temperature=0.7, do_sample=True`). `model` may be a HuggingFace Hub ID or a local path.

### Updated: `src/serve_llm/main.py`

- Uses `with TransformersPipeChannel("HuggingFaceTB/SmolLM2-135M-Instruct", max_new_tokens=256, temperature=0.7, do_sample=True) as ch:` context manager (matching the existing `serve_llm/main.py` pattern)
- Calls `ch.listen()` and `done.wait()` inside the `with` block
- Removes all old `BasicPipeChannel` handlers (ping, greet, echo, time, send_bytes)

### Updated: `src/named_pipes/__init__.py`

- Imports and exports `TransformersPipeChannel`

## Data Flow

```
C# client                          Python serve_llm
---------                          ----------------
CHAT {"role":"user","content":"Hi"}
  ──────────── cmd-upstream ──────►
                                   apply_chat_template
                                   model.generate(...)
                                   decode new tokens
  ◄──────────  cmd-downstream ──── CHAT_RESPONSE "Hello! How can I help?"
```

## Error Handling

- If `data` is not valid JSON, the handler should catch `json.JSONDecodeError` and send `ERROR` with a message.
- Model loading failures propagate as exceptions at startup (before `listen()`), which is acceptable for a PoC.

## Testing

Manual: run `python src/serve_llm/main.py`, connect a C# client or a second Python process using `BasicPipeChannel` in `Role.CLIENT` mode, send a `CHAT` message, verify `CHAT_RESPONSE` arrives.
