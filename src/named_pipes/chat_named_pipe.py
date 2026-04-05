"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

ChatNamedPipe — ToolNamedPipe subclass that serves LLM chat inference.
"""

from enum import Enum

from named_pipes.tool_named_pipe import ToolNamedPipe, Role


class Backend(Enum):
    VLLM = "vllm"
    TRANSFORMERS = "transformers"


class ChatNamedPipe(ToolNamedPipe):
    """ToolNamedPipe subclass that serves LLM chat inference.

    Supports two backends selectable via the ``backend`` parameter:

    * ``Backend.VLLM`` (default) — uses vLLM; extra kwargs are forwarded to
      ``SamplingParams`` (e.g. ``temperature=0.7``, ``max_tokens=512``).
    * ``Backend.TRANSFORMERS`` — uses HuggingFace Transformers; extra kwargs
      are forwarded to ``model.generate``
      (e.g. ``max_new_tokens=256``, ``do_sample=True``).

    Backend libraries are imported lazily inside ``__init__`` so that the
    module can be loaded on platforms where only one backend is installed.

    The ``chat`` command expects a message dict of the form::

        {"pid": ..., "cmd": "chat", "messages": [{"role": ..., "content": ...}, ...]}

    and replies via ``send_response`` with the assistant text.
    """

    def __init__(
        self,
        name: str,
        model: str,
        role: Role = Role.SERVER,
        *,
        backend: Backend = Backend.VLLM,
        description: str,
        help_text: str | None = None,
        **backend_kwargs,
    ):
        super().__init__(name, role, description=description, help_text=help_text)

        match backend:
            case Backend.VLLM:
                self._init_vllm(model, **backend_kwargs)
            case Backend.TRANSFORMERS:
                self._init_transformers(model, **backend_kwargs)
            case _:
                raise ValueError(f"unknown backend: {backend!r}")

        @self.handler("chat")
        def on_chat(msg: dict):
            messages = msg.get("messages", [])
            reply = self._infer(messages)
            self.send_response(reply)

    def _init_vllm(self, model: str, **sampling_kwargs):
        from vllm import LLM, SamplingParams

        self._llm = LLM(model=model)
        self._sampling_params = SamplingParams(**sampling_kwargs)

        def infer(messages):
            outputs = self._llm.chat(messages, self._sampling_params)
            return outputs[0].outputs[0].text

        self._infer = infer

    def _init_transformers(self, model: str, **generation_kwargs):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

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
            input_ids = self._tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt",
            ).to(self._device)
            output_ids = self._model.generate(input_ids, **self._generation_kwargs)
            new_tokens = output_ids[0][input_ids.shape[-1] :]
            return self._tokenizer.decode(new_tokens, skip_special_tokens=True)

        self._infer = infer
