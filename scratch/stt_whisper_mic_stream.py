"""
Streaming microphone → Voxtral Realtime transcription using mlx-audio + Silero VAD.

Silero VAD (a small neural network) detects speech frames, replacing the
manual RMS threshold with a learned speech/silence classifier. Speech
segments are flushed to the STT model at each speech-end event.

Requirements:
    pip install mlx-audio sounddevice numpy torch
"""

import queue
import threading

import numpy as np
import sounddevice as sd
import torch

from mlx_audio.stt import load

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# MODEL_ID = "mlx-community/whisper-large-v3-turbo-asr-fp16"
MODEL_ID = "mlx-community/Voxtral-Mini-4B-Realtime-2602-4bit"
SAMPLE_RATE = 16_000  # Whisper and Silero both expect 16 kHz mono
VAD_CHUNK = 512  # Silero's recommended window size at 16 kHz (32 ms)
MIN_SPEECH_SECONDS = 0.5  # discard segments shorter than this

_MIN_SPEECH_SAMPLES = int(MIN_SPEECH_SECONDS * SAMPLE_RATE)

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
audio_queue: queue.Queue[np.ndarray | None] = queue.Queue()


def _mic_callback(indata: np.ndarray, _frames, _time, status: sd.CallbackFlags) -> None:
    """sounddevice input callback — runs on the audio thread."""
    if status:
        print(f"[sounddevice] {status}", flush=True)
    audio_queue.put(indata[:, 0].copy())  # mono float32


def _transcription_loop(stt_model, vad_iterator) -> None:
    """
    Feed mic chunks through Silero VAD. Buffer audio while speech is active
    and send the accumulated segment to Voxtral on each speech-end event.
    """
    speech_buffer: list[np.ndarray] = []
    in_speech = False

    while True:
        chunk = audio_queue.get()
        if chunk is None:
            break

        tensor = torch.from_numpy(chunk)
        event = vad_iterator(tensor)

        if event is not None:
            if "start" in event:
                in_speech = True
                speech_buffer = []

            elif "end" in event and in_speech:
                in_speech = False
                segment = np.concatenate(speech_buffer)

                if segment.size >= _MIN_SPEECH_SAMPLES:
                    # Print tokens progressively as Voxtral decodes them.
                    for token in stt_model.generate(segment, stream=True):
                        print(token, end="", flush=True)
                    print()

                speech_buffer = []

        if in_speech:
            speech_buffer.append(chunk)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print("Loading Silero VAD…")
vad_model, utils = torch.hub.load(
    "snakers4/silero-vad", "silero_vad", force_reload=False, verbose=False
)
VADIterator = utils[3]
vad_iterator = VADIterator(
    vad_model,
    threshold=0.5,
    sampling_rate=SAMPLE_RATE,
    min_silence_duration_ms=600,  # pause this long triggers speech-end
    speech_pad_ms=200,  # padding added around each speech segment
)

print("Loading Voxtral model…")
stt_model = load(MODEL_ID)

# Warm up — avoids a long pause before the first real transcription.
_ = list(stt_model.generate(np.zeros(SAMPLE_RATE, dtype=np.float32), stream=True))

print("Listening… speak naturally and pause to transcribe. Ctrl+C to stop.\n")

transcriber = threading.Thread(
    target=_transcription_loop, args=(stt_model, vad_iterator), daemon=True
)
transcriber.start()

try:
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=VAD_CHUNK,  # deliver exactly one VAD window per callback
        callback=_mic_callback,
    ):
        threading.Event().wait()  # block until Ctrl+C
except KeyboardInterrupt:
    print("\nStopping…")
finally:
    audio_queue.put(None)
    transcriber.join(timeout=5)
    print("Done.")
