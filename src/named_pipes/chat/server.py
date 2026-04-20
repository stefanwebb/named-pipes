"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

ChatServer — ToolServer subclass that serves LLM chat inference.

Commands
--------
chat
    Streaming inference.  The server sends one ``{"event": "token",
    "text": "<chunk>", "done": false}`` event per generated token (or
    token batch), then a final ``{"event": "token", "text": "", "done":
    true}`` sentinel when generation is complete.

chat_blocking
    Non-streaming inference.  The server sends a single
    ``{"event": "reply", "text": "<full text>"}`` event when generation
    is complete.
"""

import json
import threading
from enum import Enum

from pydantic import BaseModel

from named_pipes.tool_server import ToolServer, ToolState


class Backend(Enum):
    VLLM = "vllm"
    TRANSFORMERS = "transformers"


class ChatState(Enum):
    RUNNING = ToolState.RUNNING.value
    STOPPING = ToolState.STOPPING.value
    LOADING = "loading"
    IDLE = "idle"
    INFERRING = "inferring"
    ERROR = "error"


class ChatConfig(BaseModel):
    name: str = "chat"
    model: str = "Qwen/Qwen3.5-0.8B"
    backend: Backend = Backend.TRANSFORMERS
    description: str = "LLM chat server over a named pipe."
    help_text: str | None = None
    backend_kwargs: dict = {"max_new_tokens": 256, "do_sample": False}
    verbose: bool = False


class ChatServer(ToolServer):
    """ToolServer subclass that serves LLM chat inference.

    Supports two backends selectable via the ``backend`` parameter:

    * ``Backend.VLLM`` (default) — uses vLLM; extra kwargs are forwarded to
      ``SamplingParams`` (e.g. ``temperature=0.7``, ``max_tokens=512``).
    * ``Backend.TRANSFORMERS`` — uses HuggingFace Transformers; extra kwargs
      are forwarded to ``model.generate``
      (e.g. ``max_new_tokens=256``, ``do_sample=True``).

    Backend libraries are imported lazily inside ``__init__`` so that the
    module can be loaded on platforms where only one backend is installed.

    ``chat`` command (streaming)::

        {"pid": ..., "cmd": "chat", "messages": [{"role": ..., "content": ...}, ...]}

    Replies with one or more ``{"event": "token", "text": "<chunk>", "done": false}``
    events followed by a final ``{"event": "token", "text": "", "done": true}`` sentinel.

    ``chat_blocking`` command (non-streaming)::

        {"pid": ..., "cmd": "chat_blocking", "messages": [...]}

    Replies with a single ``{"event": "reply", "text": "<full text>"}`` event.
    """

    def __init__(self, config: ChatConfig = ChatConfig()):
        super().__init__(
            config.name,
            description=config.description,
            help_text=config.help_text,
        )
        self._verbose = config.verbose
        self.set_state(ChatState.LOADING)

        try:
            match config.backend:
                case Backend.VLLM:
                    self._init_vllm(config.model, **config.backend_kwargs)
                case Backend.TRANSFORMERS:
                    self._init_transformers(config.model, **config.backend_kwargs)
                case _:
                    raise ValueError(f"unknown backend: {config.backend!r}")
        except Exception:
            self.set_state(ChatState.ERROR)
            raise

        self.set_state(ChatState.IDLE)

        self.handler("chat")(self._handle_chat)
        self.handler("chat_blocking")(self._handle_chat_blocking)

    # -----------------------------------------------------------------------
    # Command handlers
    # -----------------------------------------------------------------------
    def _handle_chat(self, msg: dict, pid: int | None):
        # Run inference on a separate thread so the listener loop is not
        # blocked while tokens are being streamed back to the client.
        # TODO: two overlapping chat requests from the same client could
        # interleave their chunks on the downstream pipe — add per-client
        # request sequencing in a future version.
        messages = msg.get("messages", [])
        threading.Thread(
            target=self._infer_stream, args=(messages, pid), daemon=True
        ).start()

    def _handle_chat_blocking(self, msg: dict, pid: int | None):
        messages = msg.get("messages", [])
        self.set_state(ChatState.INFERRING)
        try:
            reply = self._infer(messages)
        except Exception:
            self.set_state(ChatState.ERROR)
            raise
        if self._verbose:
            print(reply, flush=True)
        self.send_event("reply", pid, text=reply)
        self.set_state(ChatState.IDLE)

    # -----------------------------------------------------------------------
    # Streaming helpers
    # -----------------------------------------------------------------------

    def _send_chunk(self, text: str, pid: int | None):
        """Send one streaming chunk to *pid*."""
        if self._verbose:
            print(text, end="", flush=True)
        self.send_message(
            json.dumps({"event": "token", "text": text, "done": False}), pid
        )

    def _send_stream_done(self, pid: int | None):
        """Send the end-of-stream sentinel to *pid*."""
        if self._verbose:
            print(flush=True)
        self.send_message(json.dumps({"event": "token", "text": "", "done": True}), pid)

    # -----------------------------------------------------------------------
    # Backend initialisation
    # -----------------------------------------------------------------------

    def _init_vllm(self, model: str, **sampling_kwargs):
        from vllm import LLM, SamplingParams

        self._llm = LLM(model=model)
        self._sampling_params = SamplingParams(**sampling_kwargs)

        def infer(messages):
            outputs = self._llm.chat(messages, self._sampling_params)
            return outputs[0].outputs[0].text

        self._infer = infer

        # vLLM's synchronous LLM class does not expose token-level streaming;
        # fall back to returning the full response as a single chunk.
        def infer_stream(messages, pid):
            self.set_state(ChatState.INFERRING)
            try:
                text = infer(messages)
                self._send_chunk(text, pid)
                self._send_stream_done(pid)
            except Exception:
                self.set_state(ChatState.ERROR)
                raise
            self.set_state(ChatState.IDLE)

        self._infer_stream = infer_stream

    def _init_transformers(self, model: str, **generation_kwargs):
        import torch
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            TextIteratorStreamer,
        )

        if torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"

        self._tokenizer = AutoTokenizer.from_pretrained(model)
        self._model = AutoModelForCausalLM.from_pretrained(model).to(device)
        self._device = device
        self._generation_kwargs = generation_kwargs

        def infer(messages):
            encoded = self._tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
            ).to(device)
            prompt_len = encoded["input_ids"].shape[-1]
            output_ids = self._model.generate(**encoded, **generation_kwargs)
            new_tokens = output_ids[0][prompt_len:]
            return self._tokenizer.decode(new_tokens, skip_special_tokens=True)

        self._infer = infer

        def infer_stream(messages, pid):
            self.set_state(ChatState.INFERRING)
            try:
                encoded = self._tokenizer.apply_chat_template(
                    messages,
                    tokenize=True,
                    add_generation_prompt=True,
                    return_tensors="pt",
                    return_dict=True,
                ).to(device)
                streamer = TextIteratorStreamer(
                    self._tokenizer,
                    skip_prompt=True,
                    skip_special_tokens=True,
                )
                gen_kwargs = {**encoded, **generation_kwargs, "streamer": streamer}
                thread = threading.Thread(
                    target=self._model.generate, kwargs=gen_kwargs, daemon=True
                )
                thread.start()
                for chunk in streamer:
                    if chunk:
                        self._send_chunk(chunk, pid)
                self._send_stream_done(pid)
            except Exception:
                self.set_state(ChatState.ERROR)
                raise
            self.set_state(ChatState.IDLE)

        self._infer_stream = infer_stream
