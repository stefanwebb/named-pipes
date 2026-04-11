"""
Streaming mlx-audio TTS - plays speech through speakers as chunks are generated.

Each sentence is synthesized and queued for playback immediately, so audio
starts before the full text is done being processed.

Requirements:
    pip install mlx-audio sounddevice
"""

import queue
import threading

import numpy as np
import sounddevice as sd

from mlx_audio.tts.utils import load_model

TEXT = "Hello, world! This is a test of the mlx-audio text-to-speech library. It streams audio directly to the speakers as each chunk is generated."
VOICE = "af_heart"  # American female; see Kokoro docs for ~54 presets
SAMPLE_RATE = 24_000

# Audio chunks flow from the generator thread into this queue.
# None is the end-of-stream sentinel.
audio_queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=32)

# Leftover samples that didn't fill the last callback frame.
_remainder = np.zeros(0, dtype=np.float32)
_stop = threading.Event()


def _callback(outdata: np.ndarray, frames: int, time, status: sd.CallbackFlags) -> None:
    """sounddevice real-time callback — runs on the audio thread."""
    global _remainder

    out = np.zeros(frames, dtype=np.float32)
    pos = 0

    while pos < frames:
        # Drain the leftover buffer first.
        if _remainder.size:
            take = min(frames - pos, _remainder.size)
            out[pos : pos + take] = _remainder[:take]
            _remainder = _remainder[take:]
            pos += take
            continue

        # Pull the next chunk without blocking (silence on underrun).
        try:
            chunk = audio_queue.get_nowait()
        except queue.Empty:
            break  # fill rest with silence

        if chunk is None:
            _stop.set()
            raise sd.CallbackStop()

        _remainder = chunk

    outdata[:, 0] = out


# Load the model.
print("Loading model…")
model = load_model("mlx-community/Kokoro-82M-bf16")

# Start the output stream before generating so playback begins immediately.
stream = sd.OutputStream(
    samplerate=SAMPLE_RATE,
    channels=1,
    dtype="float32",
    blocksize=1024,
    callback=_callback,
)

print("Synthesising and streaming…")
with stream:
    for result in model.generate(TEXT, voice=VOICE, lang_code="a", speed=1.0):
        audio_queue.put(np.array(result.audio, dtype=np.float32))

    audio_queue.put(None)  # signal end of stream
    _stop.wait()  # block until the callback has played everything

print("Done.")
