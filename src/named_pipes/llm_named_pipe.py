"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

"""

"""LLMNamedPipe — ToolNamedPipe subclass that serves LLM chat inference via vLLM."""

from vllm import LLM, SamplingParams

from named_pipes.tool_named_pipe import ToolNamedPipe, Role


class LLMNamedPipe(ToolNamedPipe):
    """ToolNamedPipe subclass that serves LLM chat inference via vLLM.

    Registers a ``chat`` handler that:
      1. Reads ``messages`` from the incoming command dict
         (list of ``{"role": ..., "content": ...}`` dicts).
      2. Runs inference with the loaded vLLM model.
      3. Sends the assistant reply back via ``send_response``.

    Any keyword arguments beyond ``name``, ``model``, ``description``, and
    ``help_text`` are forwarded to ``SamplingParams``
    (e.g. ``temperature=0.7``, ``max_tokens=512``).
    """

    def __init__(
        self,
        name: str,
        model: str,
        role: Role = Role.SERVER,
        *,
        description: str,
        help_text: str | None = None,
        **sampling_kwargs,
    ):
        super().__init__(name, role, description=description, help_text=help_text)
        self._llm = LLM(model=model)
        self._sampling_params = SamplingParams(**sampling_kwargs)

        # LLM.chat() blocks the read loop for the duration of inference.
        # For concurrent requests, switch to AsyncLLMEngine.
        @self.handler("chat")
        def on_chat(msg: dict):
            messages = msg.get("messages", [])
            outputs = self._llm.chat(messages, self._sampling_params)
            reply = outputs[0].outputs[0].text
            self.send_response(reply)
