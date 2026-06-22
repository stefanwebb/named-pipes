"""© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

ForcedAligner — lazy wrapper around the mlx-audio Qwen3 forced aligner. Returns
per-word timings in seconds RELATIVE to the audio it is given.
"""

import numpy as np

from named_pipes.stt.alignment import WordTiming

DEFAULT_ALIGN_MODEL = "mlx-community/Qwen3-ForcedAligner-0.6B-4bit"


class ForcedAligner:
    """Lazily loads the MLX aligner and aligns (audio, text) pairs."""

    def __init__(self, model_id: str = DEFAULT_ALIGN_MODEL, language: str = "English"):
        self._model_id = model_id
        self._language = language
        self._model = None
        self._failed = False

    @property
    def available(self) -> bool:
        return self._model is not None and not self._failed

    def load(self) -> None:
        if self._model is not None or self._failed:
            return
        try:
            from mlx_audio.stt.utils import load_model

            self._model = load_model(self._model_id)
        except Exception:
            self._failed = True
            raise

    def align(self, audio_16k_f32: np.ndarray, text: str) -> list[WordTiming]:
        """Align ``text`` to 16 kHz mono float32 ``audio``; relative-second timings."""
        if self._model is None:
            self.load()
        result = self._model.generate(audio_16k_f32, text=text, language=self._language)
        return [
            WordTiming(str(it.text), float(it.start_time), float(it.end_time))
            for it in result
        ]
