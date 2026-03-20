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

Subclasses `BasicPipeChannel`. Constructor:

1. Calls `super().__init__(pipe_name)`
2. Detects device: `mps` → `cuda` → `cpu`
3. Loads `AutoTokenizer.from_pretrained(model)` and `AutoModelForCausalLM.from_pretrained(model)`, moves model to device
4. Registers a `CHAT` handler via `@self.handler("CHAT")`

`CHAT` handler flow:

1. `json.loads(data)` → list of `{"role": str, "content": str}` dicts
2. `tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_tensors="pt")` → input tensor on device
3. `model.generate(input_ids, max_new_tokens=..., temperature=..., do_sample=...)` → output tensor
4. Slice off prompt tokens: `output_ids[0][input_ids.shape[-1]:]`
5. `tokenizer.decode(new_tokens, skip_special_tokens=True)` → reply string
6. `self.send_message("CHAT_RESPONSE", reply)`

A comment block after the handler documents the Option B worker-thread pattern:
- A `queue.Queue` holds `(messages, reply_event)` pairs
- A dedicated inference thread owns the model and processes requests serially
- Enables future cancellation and non-blocking listener thread

Constructor accepts `**generation_kwargs` forwarded to `model.generate` (e.g. `max_new_tokens=256`, `temperature=0.7`).

### Updated: `src/serve_llm/main.py`

- Imports `TransformersPipeChannel`
- Instantiates `TransformersPipeChannel("HuggingFaceTB/SmolLM2-135M-Instruct", max_new_tokens=256)`
- Calls `ch.listen()` and `done.wait()`
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
