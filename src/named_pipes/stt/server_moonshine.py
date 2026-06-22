"""
© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en

STTServer — a named-pipe server that streams speech-to-text transcription
from a microphone to all subscribers, using Moonshine Voice.

The microphone is not opened until a "start" command is received. Before
that, clients may call "list_devices"/"get_device"/"set_device" to choose
an input device. Implements the `stt` interface
(named_pipes.interfaces.stt.STT).
"""

import threading
from enum import Enum

import sounddevice as sd
from pydantic import BaseModel

from moonshine_voice import (
    MicTranscriber,
    TranscriptEventListener,
    get_model_for_language,
)

from moonshine_voice.download import ModelArch

from named_pipes.tools.server import ToolServer, ToolState


class STTState(Enum):
    RUNNING = ToolState.RUNNING.value
    STOPPING = ToolState.STOPPING.value
    LOADING = "loading"
    READY = "ready"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    PAUSED = "paused"
    ERROR = "error"


class STTConfig(BaseModel):
    name: str = "stt"
    description: str = "👂 Real-time speech-to-text server over a named pipe."
    language: str = "en"
    device: int | None = None
    update_interval: float = 0.5
    verbose: bool = True


class _TranscriptListener(TranscriptEventListener):
    """Forwards Moonshine transcript events to the owning STTServer."""

    def __init__(self, server: "STTServer"):
        self._server = server

    def on_line_started(self, event) -> None:
        self._server._on_line_started(event.line)

    def on_line_text_changed(self, event) -> None:
        self._server._on_line_text_changed(event.line)

    def on_line_completed(self, event) -> None:
        self._server._on_line_completed(event.line)

    def on_error(self, event) -> None:
        self._server._on_error(event.error)


class STTServer(ToolServer):
    """Named-pipe STT server backed by Moonshine Voice.

    The Moonshine model is loaded eagerly on construction, but the
    microphone stream is only opened once a "start" command is received.
    """

    def __init__(self, config: STTConfig = STTConfig()):
        super().__init__(config.name, description=config.description)
        self._verbose = config.verbose
        self._device = config.device
        self._broadcast_lock = threading.Lock()

        self.set_state(STTState.LOADING)
        try:
            if self._verbose:
                print(
                    f"[STT] Loading Moonshine model for language={config.language!r}…"
                )
            model_path, model_arch = get_model_for_language(
                wanted_language=config.language,
                wanted_model_arch=ModelArch.MEDIUM_STREAMING)
            self._transcriber = MicTranscriber(
                model_path=model_path,
                model_arch=model_arch,
                update_interval=config.update_interval,
                device=self._device,
            )
            self._transcriber.add_listener(_TranscriptListener(self))
        except Exception:
            self.set_state(STTState.ERROR)
            raise

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
        self._transcriber.start()
        self.set_state(STTState.LISTENING)

    def _handle_pause(self, _msg: dict, _pid: int | None) -> None:
        self._transcriber.stop()
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

        # MicTranscriber has no public API for switching devices, so close
        # the underlying audio stream (if any) and let it reopen at the new
        # device on the next start() — resuming immediately if it was
        # already listening.
        was_listening = self._transcriber._should_listen
        if self._transcriber._sd_stream is not None:
            self._transcriber._sd_stream.stop()
            self._transcriber._sd_stream.close()
            self._transcriber._sd_stream = None
        self._transcriber._device = device
        if was_listening:
            self._transcriber.start()

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
    # Transcript event callbacks (invoked from the Moonshine listener thread)
    # -----------------------------------------------------------------------

    def _on_line_started(self, _line) -> None:
        self.set_state(STTState.TRANSCRIBING)
        with self._broadcast_lock:
            self.send_event("speech_start")

    def _on_line_text_changed(self, line) -> None:
        with self._broadcast_lock:
            self.send_event("speech", text=line.text)

    def _on_line_completed(self, line) -> None:
        with self._broadcast_lock:
            self.send_event("speech", text=line.text)
            self.send_event("speech_end")
        if self._state is STTState.TRANSCRIBING:
            self.set_state(STTState.LISTENING)

    def _on_error(self, error) -> None:
        self.set_state(STTState.ERROR)
        with self._broadcast_lock:
            self.send_event("error", message=str(error))

    # -----------------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------------

    def _close(self):
        # moonshine_voice's stop()/close() aren't idempotent, and __del__
        # calls _close() again after an explicit close — guard accordingly.
        if self._closed:
            return
        self._transcriber.stop()
        self._transcriber.close()
        super()._close()
