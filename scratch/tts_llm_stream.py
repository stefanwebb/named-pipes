"""
LLM → TTS streaming pipeline.

Text tokens arrive incrementally (simulated here with a mock LLM).
Tokens are buffered until a sentence boundary is detected, then the sentence
is synthesised and queued for real-time playback — so audio starts before
the full text is known.

Pipeline:
    token stream → [sentence splitter] → sentence_queue
                 → [TTS worker thread] → audio_queue
                 → [audio callback]    → speakers

Requirements:
    pip install mlx-audio sounddevice
"""

import queue
import re
import threading
import time

import numpy as np
import sounddevice as sd

from mlx_audio.tts.utils import load_model

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VOICE = "af_heart"
SAMPLE_RATE = 24_000
BLOCKSIZE = 1024

# Simulated LLM output — a paragraph that will be streamed token by token.
DEMO_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "It was a bright cold day in April, and the clocks were striking thirteen. "
    "All happy families are alike; each unhappy family is unhappy in its own way. "
    "It is a truth universally acknowledged, that a single man in possession of a "
    "good fortune, must be in want of a wife. "
    "Call me Ishmael."
)

# Simulated token delay — real LLMs emit ~10–50 ms per token.
TOKEN_DELAY_S = 0.04

# ---------------------------------------------------------------------------
# Mock LLM token stream
# ---------------------------------------------------------------------------


def mock_llm_token_stream(text: str, delay: float = TOKEN_DELAY_S):
    """Yield tokens one at a time, simulating an LLM streaming response."""
    # Split into ~word-sized tokens (real LLMs use sub-word pieces).
    tokens = re.findall(r"\S+\s*", text)
    for token in tokens:
        time.sleep(delay)
        yield token


# ---------------------------------------------------------------------------
# Sentence splitter
# ---------------------------------------------------------------------------

# Match a sentence-ending punctuation followed by whitespace or end-of-string.
# The lookbehind keeps the punctuation attached to the sentence.
_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def iter_sentences(token_stream):
    """
    Buffer tokens from *token_stream* and yield complete sentences.

    A sentence boundary is any .  !  ? followed by whitespace.  The final
    fragment (no trailing whitespace) is yielded when the stream ends.
    """
    buf = ""
    for token in token_stream:
        buf += token
        parts = _BOUNDARY.split(buf)
        # Every part except the last is a complete sentence.
        for sentence in parts[:-1]:
            if sentence.strip():
                yield sentence.strip()
        buf = parts[-1]  # incomplete tail — keep buffering

    if buf.strip():
        yield buf.strip()  # flush the final fragment


# ---------------------------------------------------------------------------
# Queues
# ---------------------------------------------------------------------------

sentence_queue: queue.Queue[str | None] = queue.Queue()

# Bounded so the TTS worker doesn't race too far ahead of playback.
audio_queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=64)

# ---------------------------------------------------------------------------
# TTS worker thread
# ---------------------------------------------------------------------------


def tts_worker(model) -> None:
    """
    Pull sentences from sentence_queue, synthesise them, and push audio chunks
    into audio_queue.  Runs on its own thread so synthesis overlaps playback.
    A None sentinel in sentence_queue signals shutdown.
    """
    while True:
        sentence = sentence_queue.get()
        if sentence is None:
            audio_queue.put(None)
            return
        print(f"  [TTS] synthesising: {sentence!r}")
        for result in model.generate(sentence, voice=VOICE, lang_code="a", speed=1.0):
            audio_queue.put(np.array(result.audio, dtype=np.float32))


# ---------------------------------------------------------------------------
# Audio output callback
# ---------------------------------------------------------------------------

_remainder = np.zeros(0, dtype=np.float32)
_stop_event = threading.Event()


def _audio_callback(
    outdata: np.ndarray, frames: int, _time, _status: sd.CallbackFlags
) -> None:
    """
    Real-time audio callback.  Drains audio_queue at exactly playback speed.
    Fills any underrun with silence rather than blocking.
    """
    global _remainder

    out = np.zeros(frames, dtype=np.float32)
    pos = 0

    while pos < frames:
        # Use up any leftover samples from the previous chunk first.
        if _remainder.size:
            take = min(frames - pos, _remainder.size)
            out[pos : pos + take] = _remainder[:take]
            _remainder = _remainder[take:]
            pos += take
            continue

        # Pull the next chunk without blocking.
        try:
            chunk = audio_queue.get_nowait()
        except queue.Empty:
            break  # underrun — pad with silence

        if chunk is None:
            _stop_event.set()
            raise sd.CallbackStop()

        _remainder = chunk

    outdata[:, 0] = out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("Loading TTS model…")
    model = load_model("mlx-community/Kokoro-82M-bf16")

    # Start the TTS worker before the audio stream so the first sentence can
    # be synthesised while the stream is opening.
    worker = threading.Thread(target=tts_worker, args=(model,), daemon=True)
    worker.start()

    print("Starting audio stream…")
    with sd.OutputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=BLOCKSIZE,
        callback=_audio_callback,
    ):
        print("Streaming tokens → sentences → audio…\n")

        token_stream = mock_llm_token_stream(DEMO_TEXT)

        for sentence in iter_sentences(token_stream):
            print(f"  [LLM] sentence ready: {sentence!r}")
            sentence_queue.put(sentence)

        sentence_queue.put(None)  # tell TTS worker to stop after current queue
        _stop_event.wait()  # block until the audio callback drains

    print("\nDone.")


if __name__ == "__main__":
    main()
