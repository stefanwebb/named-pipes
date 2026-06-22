"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

STTServer — a named-pipe server that streams speech-to-text transcription
from a microphone to all subscribers, using the vendored Voxtral streaming
decoder with Silero VAD.

The microphone is not opened until a "start" command is received. Before
that, clients may call "list_devices"/"get_device"/"set_device" to choose
an input device. Implements the `stt` interface
(named_pipes.interfaces.stt.STT).
"""

import threading
from enum import Enum

import numpy as np
import sounddevice as sd
from pydantic import BaseModel

from named_pipes.stt.alignment import (
    CoalescingAligner,
    detect_word_boundary,
    to_absolute,
)
from named_pipes.stt.voxtral.stream import stream_transcribe
from named_pipes.tools.server import ToolServer, ToolState


class STTState(Enum):
    RUNNING = ToolState.RUNNING.value
    STOPPING = ToolState.STOPPING.value
    READY = "ready"
    LOADING = "loading"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    PAUSED = "paused"
    ERROR = "error"


class STTConfig(BaseModel):
    name: str = "stt"
    description: str = "👂 Real-time speech-to-text server over a named pipe."
    model_path: str = "mlx-community/Voxtral-Mini-4B-Realtime-6bit"
    temperature: float = 0.0
    vad_onset: int = 2
    vad_offset: int = 32
    device: int | None = None
    align: bool = False
    align_language: str = "English"
    align_model: str = "mlx-community/Qwen3-ForcedAligner-0.6B-4bit"
    verbose: bool = True


class STTServer(ToolServer):
    """Named-pipe STT server backed by the vendored Voxtral streaming decoder.

    The Voxtral model and VAD are loaded lazily on the first "start"
    command rather than at construction time, so that "list_devices" /
    "get_device" / "set_device" are available immediately.
    """

    def __init__(self, config: STTConfig = STTConfig(), aligner=None):
        super().__init__(config.name, description=config.description)
        self._config = config
        self._device = config.device
        self._current_text = ""
        self._broadcast_lock = threading.Lock()
        self._stop_event: threading.Event | None = None
        self._worker: threading.Thread | None = None

        # Per-utterance forced-alignment state.
        self._utt_audio = np.zeros(0, dtype=np.float32)
        self._utt_abs_start = 0.0
        self._coalescer = None
        if config.align:
            if aligner is None:
                from named_pipes.stt.aligner import ForcedAligner

                aligner = ForcedAligner(config.align_model, config.align_language)
            self._aligner = aligner
            self._coalescer = CoalescingAligner(
                align_fn=self._aligner.align,
                emit_fn=self._emit_words,
                on_error=self._on_align_error,
            )

        self.set_state(STTState.READY)

        self.handler("start")(self._handle_start)
        self.handler("pause")(self._handle_pause)
        self.handler("list_devices")(self._handle_list_devices)
        self.handler("get_device")(self._handle_get_device)
        self.handler("set_device")(self._handle_set_device)

    def _list_interfaces(self) -> list[str]:
        return super()._list_interfaces() + ["stt"]

    # -----------------------------------------------------------------------
    # Command handlers
    # -----------------------------------------------------------------------

    def _handle_start(self, _msg: dict, _pid: int | None) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self.set_state(STTState.LOADING)
        self._stop_event = threading.Event()
        self._worker = threading.Thread(
            target=stream_transcribe,
            kwargs={
                "model_path": self._config.model_path,
                "temperature": self._config.temperature,
                "vad_onset": self._config.vad_onset,
                "vad_offset": self._config.vad_offset,
                "device": self._device,
                "verbose": self._config.verbose,
                "on_token": self._on_token,
                "on_speaking_started": self._on_start,
                "on_speaking_finished": self._on_end,
                "on_ready": self._on_ready,
                "on_audio": self._on_audio,
                "stop_event": self._stop_event,
            },
            daemon=True,
            name="stt-worker",
        )
        self._worker.start()

    def _handle_pause(self, _msg: dict, _pid: int | None) -> None:
        if self._stop_event is None:
            return
        self._stop_event.set()
        self._worker.join(timeout=10)
        self._worker = None
        self._stop_event = None
        self.set_state(STTState.PAUSED)

    def _handle_list_devices(self, _msg: dict, pid: int | None) -> None:
        devices = [
            {"index": i, "name": info["name"], "channels": info["max_input_channels"]}
            for i, info in enumerate(sd.query_devices())
            if info["max_input_channels"] > 0
        ]
        self.send_event("devices", pid, devices=devices)

    def _handle_get_device(self, _msg: dict, pid: int | None) -> None:
        self.send_event("device", pid, device=self._device)

    def _handle_set_device(self, msg: dict, pid: int | None) -> None:
        try:
            device = self._resolve_device(msg.get("device"))
        except ValueError as e:
            self.send_event("error", pid, message=str(e))
            return

        self._device = device

        # The Voxtral worker has no live device-switch primitive — if it's
        # currently running, pause and restart it on the new device.
        was_listening = self._worker is not None and self._worker.is_alive()
        if was_listening:
            self._handle_pause(msg, pid)
            self._handle_start(msg, pid)

        self.send_event("device", pid, device=device)

    def _resolve_device(self, value) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
        name = str(value).lower()
        for i, info in enumerate(sd.query_devices()):
            if info["max_input_channels"] > 0 and name in info["name"].lower():
                return i
        raise ValueError(f"no input device matching {value!r}")

    # -----------------------------------------------------------------------
    # Voxtral worker callbacks (invoked from the stt-worker thread)
    # -----------------------------------------------------------------------

    def _on_ready(self) -> None:
        self.set_state(STTState.LISTENING)

    def _on_token(self, text: str) -> None:
        if self._coalescer is not None and detect_word_boundary(
            self._current_text, text
        ):
            if self._current_text.strip():
                self._coalescer.submit(
                    self._utt_audio.copy(), self._current_text, self._utt_abs_start
                )
        self._current_text += text
        with self._broadcast_lock:
            self.send_event("token", text=text)
            self.send_event("speech", text=self._current_text)

    def _on_start(self, abs_start: float = 0.0) -> None:
        self._current_text = ""
        self._utt_audio = np.zeros(0, dtype=np.float32)
        self._utt_abs_start = abs_start
        self.set_state(STTState.TRANSCRIBING)
        with self._broadcast_lock:
            self.send_event("speech_start")

    def _on_audio(self, chunk) -> None:
        if self._coalescer is not None:
            self._utt_audio = np.append(self._utt_audio, chunk)

    def _on_end(self) -> None:
        with self._broadcast_lock:
            self.send_event("speech_end")
        if self._coalescer is not None and self._current_text.strip():
            self._coalescer.submit(
                self._utt_audio.copy(), self._current_text, self._utt_abs_start
            )
        if self._state is STTState.TRANSCRIBING:
            self.set_state(STTState.LISTENING)

    def _emit_words(self, items, text: str, abs_start: float) -> None:
        words = to_absolute(items, abs_start)
        with self._broadcast_lock:
            self.send_event("speech", text=text, words=words)

    def _on_align_error(self, exc: Exception) -> None:
        if self._config.verbose:
            print(f"[STT] alignment error: {exc}", flush=True)

    # -----------------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------------

    def _close(self):
        if self._closed:
            return
        if self._coalescer is not None:
            self._coalescer.stop()
        if self._stop_event is not None:
            self._stop_event.set()
        if self._worker is not None:
            self._worker.join(timeout=5)
        super()._close()
