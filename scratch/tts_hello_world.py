"""
Minimal Voxtral 4B TTS - generates audio for "Hello, world!" using vllm-omni offline Python API.

Requirements:
    pip install vllm vllm-omni mistral-common soundfile torch
"""

import torch
import soundfile as sf
from pathlib import Path

from mistral_common.protocol.speech.request import SpeechRequest
from mistral_common.tokens.tokenizers.mistral import MistralTokenizer
from vllm import SamplingParams
from vllm_omni.entrypoints.omni import Omni

MODEL = "mistralai/Voxtral-4B-TTS-2603"
VOICE = "casual_male"
TEXT = "Hello, world!"
OUTPUT = "hello_world.wav"
SAMPLE_RATE = 24000

# Build tokenized input
if Path(MODEL).is_dir():
    tokenizer = MistralTokenizer.from_file(str(Path(MODEL) / "tekken.json"))
else:
    tokenizer = MistralTokenizer.from_hf_hub(MODEL)

tokenized = tokenizer.instruct_tokenizer.encode_speech_request(
    SpeechRequest(input=TEXT, voice=VOICE)
)

inputs = {
    "prompt_token_ids": tokenized.tokens,
    "additional_information": {"voice": [VOICE]},
}

# Two SamplingParams entries — one per model stage
sampling_params = SamplingParams(max_tokens=2500)
sampling_params_list = [sampling_params, sampling_params]

# Run inference
llm = Omni(model=MODEL)
outputs = llm.generate(inputs, sampling_params_list)

# Save audio
audio_tensor = torch.cat(outputs[0].multimodal_output["audio"])
audio_array = audio_tensor.float().cpu().numpy()
sf.write(OUTPUT, audio_array, SAMPLE_RATE)
print(f"Saved {len(audio_array) / SAMPLE_RATE:.2f}s of audio to {OUTPUT}")
