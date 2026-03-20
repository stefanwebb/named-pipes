import json

from vllm import LLM, SamplingParams

from named_pipes.basic_pipe_channel import BasicPipeChannel


class LLMPipeChannel(BasicPipeChannel):
    """PipeChannel subclass that serves LLM chat inference via vLLM.

    Registers a CHAT handler that:
      1. Deserializes the incoming data as a JSON conversation
         (list of {"role": ..., "content": ...} dicts).
      2. Runs inference with the loaded vLLM model.
      3. Sends the assistant reply back as CHAT_RESPONSE.

    Any keyword arguments beyond `model` and `pipe_name` are forwarded
    to SamplingParams (e.g. temperature=0.7, max_tokens=512).
    """

    def __init__(self, model: str, pipe_name: str = "/tmp/agent", **sampling_kwargs):
        super().__init__(pipe_name)
        self._llm = LLM(model=model)
        self._sampling_params = SamplingParams(**sampling_kwargs)

        # LLM.chat() blocks the read loop for the duration of inference.
        # For concurrent requests, switch to AsyncLLMEngine.
        @self.handler("CHAT")
        def on_chat(data: str):
            messages = json.loads(data)
            outputs = self._llm.chat(messages, self._sampling_params)
            reply = outputs[0].outputs[0].text
            self.send_message("CHAT_RESPONSE", reply)
