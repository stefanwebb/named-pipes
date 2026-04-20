"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

STTServer — a named-pipe server that streams speech-to-text transcription
from the default microphone to all subscribers.

On construction the class starts a background thread running the vendored
voxtral stream_transcribe loop. Per-token output is broadcast as
{"event": "token", "text": "<token>"}; VAD lifecycle events are broadcast as
{"event": "speech_start"} / {"event": "speech_end"}. The tool has no custom
commands — it is producer-only.
"""

import json
import threading
from enum import Enum

from pydantic import BaseModel

from named_pipes.stt.voxtral.stream import stream_transcribe
from named_pipes.tool_server import ToolServer, ToolState


class STTState(Enum):
    RUNNING = ToolState.RUNNING.value
    STOPPING = ToolState.STOPPING.value
    LOADING = "loading"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    ERROR = "error"


class STTConfig(BaseModel):
    name: str = "stt"
    model_path: str = "mlx-community/Voxtral-Mini-4B-Realtime-6bit"
    temperature: float = 0.0
    vad_onset: int = 2
    vad_offset: int = 32
    verbose: bool = False


class STTServer(ToolServer):
    """Named-pipe STT server.

    Starts the microphone and the Voxtral streaming decode loop in a daemon
    thread immediately on construction. Tokens and VAD lifecycle events are
    broadcast to every subscriber as JSON messages.
    """

    def __init__(self, config: STTConfig = STTConfig()):
        super().__init__(
            config.name,
            description="Real-time speech-to-text server over a named pipe.",
        )
        self.set_state(STTState.LOADING)
        self._stop_event = threading.Event()
        self._broadcast_lock = threading.Lock()

        self._worker = threading.Thread(
            target=stream_transcribe,
            kwargs={
                "model_path": config.model_path,
                "temperature": config.temperature,
                "vad_onset": config.vad_onset,
                "vad_offset": config.vad_offset,
                "verbose": config.verbose,
                "on_token": self._on_token,
                "on_speaking_started": self._on_start,
                "on_speaking_finished": self._on_end,
                "on_ready": self._on_ready,
                "stop_event": self._stop_event,
            },
            daemon=True,
            name="stt-worker",
        )
        self._worker.start()

    def _on_ready(self) -> None:
        self.set_state(STTState.LISTENING)

    def _on_token(self, text: str) -> None:
        with self._broadcast_lock:
            self.broadcast_message(json.dumps({"event": "token", "text": text}))

    def _on_start(self) -> None:
        self.set_state(STTState.TRANSCRIBING)
        with self._broadcast_lock:
            self.broadcast_message(json.dumps({"event": "speech_start"}))

    def _on_end(self) -> None:
        self.set_state(STTState.LISTENING)
        with self._broadcast_lock:
            self.broadcast_message(json.dumps({"event": "speech_end"}))

    def _close(self):
        self._stop_event.set()
        self._worker.join(timeout=5)
        super()._close()
