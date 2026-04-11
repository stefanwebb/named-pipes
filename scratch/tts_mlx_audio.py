"""
Minimal mlx-audio TTS example - generates audio using Kokoro-82M on Apple Silicon.

Requirements:
    pip install mlx-audio soundfile
"""

import numpy as np
import soundfile as sf

from mlx_audio.tts.utils import load_model

TEXT = "Hello, world! This is a test of the mlx-audio text-to-speech library."
VOICE = "af_heart"  # American female; see Kokoro docs for ~54 presets
SAMPLE_RATE = 24_000
OUTPUT = "tts_output.wav"

model = load_model("mlx-community/Kokoro-82M-bf16")

chunks = []
for result in model.generate(TEXT, voice=VOICE, lang_code="a", speed=1.0):
    chunks.append(np.array(result.audio))

audio = np.concatenate(chunks)
sf.write(OUTPUT, audio, samplerate=SAMPLE_RATE)
print(f"Saved {len(audio) / SAMPLE_RATE:.2f}s of audio to {OUTPUT}")
