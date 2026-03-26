import json

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from named_pipes.basic_pipe_channel import BasicPipeChannel


class TransformersPipeChannel(BasicPipeChannel):
    """PipeChannel subclass that serves LLM chat inference via HuggingFace transformers.

    Registers a CHAT handler that:
      1. Deserializes the incoming data as a JSON conversation
         (list of {"role": ..., "content": ...} dicts).
      2. Runs inference with the loaded transformers model.
      3. Sends the assistant reply back as CHAT_RESPONSE.

    Any keyword arguments beyond `model` and `pipe_name` are forwarded
    to model.generate (e.g. max_new_tokens=256, temperature=0.7, do_sample=True).
    Note: temperature requires do_sample=True to take effect.

    # Option B worker-thread pattern (future work):
    # A queue.Queue holds (messages, reply_event) pairs.
    # A dedicated inference thread owns the model and processes requests serially.
    # This would enable future cancellation and non-blocking listener thread,
    # and also unblock QUIT handling during inference (currently blocked with Option A).
    """

    def __init__(self, model: str, pipe_name: str = "/tmp/agent", **generation_kwargs):
        super().__init__(pipe_name)

        if torch.backends.mps.is_available():
            self._device = "mps"
        elif torch.cuda.is_available():
            self._device = "cuda"
        else:
            self._device = "cpu"

        self._tokenizer = AutoTokenizer.from_pretrained(model)
        self._model = AutoModelForCausalLM.from_pretrained(model).to(self._device)
        self._generation_kwargs = generation_kwargs

        @self.handler("CHAT")
        def on_chat(data: str):
            try:
                messages = json.loads(data)
            except json.JSONDecodeError:
                self.send_message("ERROR", "invalid JSON")
                return

            input_ids = self._tokenizer.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt",
            ).to(self._device)

            output_ids = self._model.generate(input_ids, **self._generation_kwargs)
            new_tokens = output_ids[0][input_ids.shape[-1] :]
            reply = self._tokenizer.decode(new_tokens, skip_special_tokens=True)
            self.send_message("CHAT_RESPONSE", reply)
