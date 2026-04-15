"""
Streaming microphone → Whisper transcription using mlx-audio.

Audio is buffered continuously and sent to Whisper only when a silence gap
is detected, so each transcribed segment aligns with a natural speech pause
rather than a fixed-length window.

Requirements:
    pip install mlx-audio sounddevice numpy
"""

import queue
import threading

import numpy as np
import sounddevice as sd

from mlx_audio.stt import load

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL_ID = "mlx-community/whisper-large-v3-turbo-asr-fp16"
SAMPLE_RATE = 16_000  # Whisper expects 16 kHz mono
SILENCE_THRESHOLD = 0.02  # RMS below this level is considered silence
SILENCE_SECONDS = 0.8  # pause this long triggers transcription
MIN_SPEECH_SECONDS = (
    0.3  # minimum loud frames required to transcribe (raise if hallucinating)
)

_SILENCE_FRAMES = int(SILENCE_SECONDS * SAMPLE_RATE)
_MIN_SPEECH_FRAMES = int(MIN_SPEECH_SECONDS * SAMPLE_RATE)

# ---------------------------------------------------------------------------
# Shared state between mic callback and transcription thread
# ---------------------------------------------------------------------------
audio_queue: queue.Queue[np.ndarray | None] = queue.Queue()


def _mic_callback(indata: np.ndarray, _frames, _time, status: sd.CallbackFlags) -> None:
    """sounddevice input callback — runs on the audio thread."""
    if status:
        print(f"[sounddevice] {status}", flush=True)
    audio_queue.put(indata[:, 0].copy())  # mono float32


def _transcription_loop(model) -> None:
    """
    Drain the audio queue.  Accumulate samples into a speech buffer and flush
    it to Whisper whenever a long enough silence follows audible speech.
    Only transcribe if the buffer contains enough genuinely loud frames —
    this prevents Whisper hallucinations on near-silent ambient noise.
    """
    speech_buffer = np.zeros(0, dtype=np.float32)
    silent_frames = 0
    loud_frames = 0  # frames whose RMS was >= SILENCE_THRESHOLD

    while True:
        chunk = audio_queue.get()
        if chunk is None:
            break

        rms = float(np.sqrt(np.mean(chunk**2)))

        if rms >= SILENCE_THRESHOLD:
            speech_buffer = np.concatenate([speech_buffer, chunk])
            loud_frames += len(chunk)
            silent_frames = 0
        else:
            speech_buffer = np.concatenate([speech_buffer, chunk])
            silent_frames += len(chunk)

            if silent_frames >= _SILENCE_FRAMES:
                if loud_frames >= _MIN_SPEECH_FRAMES:
                    segment = speech_buffer.copy()

                    result = model.generate(segment, language="en", verbose=None)
                    text = (
                        result.text.strip()
                        if hasattr(result, "text")
                        else str(result).strip()
                    )
                    if text:
                        print(text, flush=True)

                # Reset regardless — discard noise-only buffers silently.
                speech_buffer = np.zeros(0, dtype=np.float32)
                silent_frames = 0
                loud_frames = 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print("Loading Whisper model…")
model = load(MODEL_ID)

# Warm up — avoids a long pause before the first real transcription.
_ = model.generate(np.zeros(SAMPLE_RATE, dtype=np.float32), language="en", verbose=None)

print("Listening… speak naturally and pause to transcribe. Ctrl+C to stop.\n")

transcriber = threading.Thread(target=_transcription_loop, args=(model,), daemon=True)
transcriber.start()

try:
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        callback=_mic_callback,
    ):
        threading.Event().wait()  # block until Ctrl+C
except KeyboardInterrupt:
    print("\nStopping…")
finally:
    audio_queue.put(None)
    transcriber.join(timeout=5)
    print("Done.")
