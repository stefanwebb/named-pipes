"""
Streaming microphone → Voxtral Realtime transcription using mlx-audio + Silero VAD.

Silero VAD (a small neural network) detects speech frames, replacing the
manual RMS threshold with a learned speech/silence classifier. Speech
segments are dispatched to a thread pool on each speech-end event so the
VAD loop is never blocked during inference.

Requirements:
    pip install mlx-audio sounddevice numpy torch
"""

import queue
import threading
from concurrent.futures import ThreadPoolExecutor

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
PARTIAL_SECONDS = 0.5  # submit a partial transcription after this much speech

_MIN_SPEECH_SAMPLES = int(MIN_SPEECH_SECONDS * SAMPLE_RATE)
_PARTIAL_SAMPLES = int(PARTIAL_SECONDS * SAMPLE_RATE)

# Serialises print calls across concurrent transcription threads.
_print_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
audio_queue: queue.Queue[np.ndarray | None] = queue.Queue()


def on_speech_start() -> None:
    print("Speaking started...", flush=True)


def on_speech_end() -> None:
    print("Speaking ended...", flush=True)


def _mic_callback(indata: np.ndarray, _frames, _time, status: sd.CallbackFlags) -> None:
    """sounddevice input callback — runs on the audio thread."""
    if status:
        print(f"[sounddevice] {status}", flush=True)
    audio_queue.put(indata[:, 0].copy())  # mono float32


def _transcribe(stt_model, segment: np.ndarray) -> None:
    """Transcribe one speech segment and print tokens as they arrive."""
    with _print_lock:
        for token in stt_model.generate(
            segment, transcription_delay_ms=240, stream=True
        ):
            print(token, end="", flush=True)
        print()


def _transcription_loop(stt_model, vad_iterator, executor: ThreadPoolExecutor) -> None:
    """
    Feed mic chunks through Silero VAD. While speech is active, dispatch a
    partial transcription every PARTIAL_SECONDS so text appears during speech.
    The remaining tail is dispatched on speech-end.
    """
    speech_buffer: list[np.ndarray] = []
    buffered_samples = 0
    dispatched_samples = 0
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
                buffered_samples = 0
                dispatched_samples = 0
                on_speech_start()

            elif "end" in event and in_speech:
                in_speech = False
                on_speech_end()
                # Dispatch whatever speech hasn't been transcribed yet.
                tail = np.concatenate(speech_buffer)
                speech_buffer = []
                if tail.size >= _MIN_SPEECH_SAMPLES:
                    executor.submit(_transcribe, stt_model, tail)
                buffered_samples = 0
                dispatched_samples = 0

        if in_speech:
            speech_buffer.append(chunk)
            buffered_samples += len(chunk)

            # Every PARTIAL_SECONDS, snapshot and dispatch what we have so far.
            undispatched = buffered_samples - dispatched_samples
            if undispatched >= _PARTIAL_SAMPLES:
                partial = np.concatenate(speech_buffer)
                speech_buffer = []
                buffered_samples = 0
                dispatched_samples += len(partial)
                executor.submit(_transcribe, stt_model, partial)


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

with ThreadPoolExecutor(max_workers=2) as executor:
    transcriber = threading.Thread(
        target=_transcription_loop,
        args=(stt_model, vad_iterator, executor),
        daemon=True,
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
