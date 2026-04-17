"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

TTSNamedPipe — a named-pipe tool that streams TTS audio in real time.

Incoming text tokens are buffered until a sentence boundary is detected,
then the sentence is synthesised and queued for playback.

Pipeline:
    text messages → [sentence splitter] → sentence_queue
                  → [TTS worker thread] → audio_queue
                  → [audio callback]    → speakers

Supported commands (in addition to ToolNamedPipe builtins):
    {"pid": <int>, "cmd": "text", "data": "<tokens>"}
        Append tokens to the text buffer.  When a sentence boundary
        (. ! ? followed by whitespace) is detected the sentence is
        pushed to the TTS queue automatically.

    {"pid": <int>, "cmd": "flush"}
        Force-push whatever remains in the text buffer as a sentence,
        even if no boundary has been detected yet.  Use at the end of a
        generation to drain the final fragment.
"""

import queue
import re
import threading

import numpy as np
import sounddevice as sd
from pydantic import BaseModel

from mlx_audio.tts.utils import load_model

from named_pipes.text_named_pipe import Role
from named_pipes.tool_named_pipe import ToolNamedPipe

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VOICE = "af_heart"
SAMPLE_RATE = 24_000
BLOCKSIZE = 1024
MODEL_ID = "mlx-community/Kokoro-82M-bf16"


class TTSConfig(BaseModel):
    name: str = "tts"
    voice: str = VOICE
    sample_rate: int = SAMPLE_RATE
    blocksize: int = BLOCKSIZE
    model_id: str = MODEL_ID


# Sentence boundary: . ! ? followed by whitespace or end-of-string.
_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


# ---------------------------------------------------------------------------
# TTSNamedPipe
# ---------------------------------------------------------------------------


class TTSNamedPipe(ToolNamedPipe):
    """Named-pipe TTS server.

    Listens for ``text`` and ``flush`` commands, accumulates tokens into
    sentences, synthesises them with Kokoro (via mlx-audio), and plays the
    audio through sounddevice in real time.
    """

    def __init__(self, config: TTSConfig = TTSConfig()):
        super().__init__(
            config.name,
            Role.SERVER,
            description="Real-time text-to-speech server over a named pipe.",
        )
        self._voice = config.voice
        self._sample_rate = config.sample_rate
        self._blocksize = config.blocksize

        # Text accumulation buffer (accessed only from the listener thread).
        self._buf = ""

        # Inter-thread queues.
        self._sentence_queue: queue.Queue[str | None] = queue.Queue()
        self._audio_queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=64)

        # Audio callback state.
        self._remainder = np.zeros(0, dtype=np.float32)
        self._audio_done = threading.Event()

        # Load model and start the TTS worker thread.
        print(f"[TTS] Loading model {config.model_id!r}…")
        self._model = load_model(config.model_id)

        self._tts_thread = threading.Thread(
            target=self._tts_worker, daemon=True, name="tts-worker"
        )
        self._tts_thread.start()

        # Open the audio output stream (kept alive for the lifetime of the server).
        self._stream = sd.OutputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self._blocksize,
            callback=self._audio_callback,
        )
        self._stream.start()
        print("[TTS] Audio stream started.")

        # Register protocol handlers.
        self.handler("text")(self._handle_text)
        self.handler("flush")(self._handle_flush)

    # -----------------------------------------------------------------------
    # Command handlers
    # -----------------------------------------------------------------------

    def _handle_text(self, msg: dict, pid: int | None) -> None:
        """Append token(s) to the buffer; emit sentences when boundaries found."""
        token = msg.get("data", "")
        if not token:
            return
        self._buf += token
        parts = _BOUNDARY.split(self._buf)
        # Every part except the last is a complete sentence.
        for sentence in parts[:-1]:
            if sentence.strip():
                self._sentence_queue.put(sentence.strip())
        self._buf = parts[-1]

    def _handle_flush(self, msg: dict, pid: int | None) -> None:
        """Push any remaining buffer content as a sentence."""
        if self._buf.strip():
            self._sentence_queue.put(self._buf.strip())
            self._buf = ""

    # -----------------------------------------------------------------------
    # TTS worker
    # -----------------------------------------------------------------------

    def _tts_worker(self) -> None:
        """Synthesise sentences from sentence_queue and push audio to audio_queue."""
        while True:
            sentence = self._sentence_queue.get()
            if sentence is None:
                self._audio_queue.put(None)
                return
            print(f"  [TTS] synthesising: {sentence!r}")
            for result in self._model.generate(
                sentence, voice=self._voice, lang_code="a", speed=1.0
            ):
                self._audio_queue.put(np.array(result.audio, dtype=np.float32))

    # -----------------------------------------------------------------------
    # Audio callback
    # -----------------------------------------------------------------------

    def _audio_callback(
        self, outdata: np.ndarray, frames: int, _time, _status: sd.CallbackFlags
    ) -> None:
        """Drain audio_queue at exactly playback speed; pad underruns with silence."""
        out = np.zeros(frames, dtype=np.float32)
        pos = 0

        while pos < frames:
            if self._remainder.size:
                take = min(frames - pos, self._remainder.size)
                out[pos : pos + take] = self._remainder[:take]
                self._remainder = self._remainder[take:]
                pos += take
                continue

            try:
                chunk = self._audio_queue.get_nowait()
            except queue.Empty:
                break  # underrun — pad remainder with silence

            if chunk is None:
                self._audio_done.set()
                raise sd.CallbackStop()

            self._remainder = chunk

        outdata[:, 0] = out

    # -----------------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------------

    def _close(self):
        # Signal the TTS worker to stop, then stop the audio stream.
        self._sentence_queue.put(None)
        self._tts_thread.join(timeout=5)
        self._stream.stop()
        self._stream.close()
        super()._close()
