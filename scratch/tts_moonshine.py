"""
Streaming microphone transcription using Moonshine Voice (moonshine-voice).

Moonshine Voice ships native ONNX Runtime bindings and runs entirely on CPU —
there's no Metal/CoreML execution path to opt into, but that's by design: the
project explicitly avoids GPU/NPU acceleration to stay portable. On Apple
Silicon this is still fast since the streaming models are small (34-245M
params) and onnxruntime uses Arm NEON.

Model weights are NOT on Hugging Face Hub. `get_model_for_language()` below
downloads quantized .ort files straight from Moonshine's own CDN
(https://download.moonshine.ai/model/...) into the local cache dir — neither
the `mlx-community` org nor `UsefulSensors/moonshine` on HF are used by this
package. UsefulSensors/moonshine on HF hosts the original (now superseded)
research checkpoints from before the project moved to its own CDN.

Requirements:
    pip install moonshine-voice
"""

import sys
import time

import sounddevice as sd

from moonshine_voice import (
    MicTranscriber,
    TranscriptEventListener,
    get_model_for_language,
)

LANGUAGE = "en"
MODEL_ARCH = None  # None picks the default model for LANGUAGE (tiny-streaming-en)
MIC_DEVICE = None  # PortAudio input device index; None = host default


class TerminalListener(TranscriptEventListener):
    def __init__(self) -> None:
        self.last_line_length = 0

    def _overwrite_line(self, text: str) -> None:
        print(f"\r{text}", end="", flush=True)
        if len(text) < self.last_line_length:
            print(" " * (self.last_line_length - len(text)), end="", flush=True)
        self.last_line_length = len(text)

    def on_line_started(self, event) -> None:
        self.last_line_length = 0

    def on_line_text_changed(self, event) -> None:
        self._overwrite_line(event.line.text)

    def on_line_completed(self, event) -> None:
        self._overwrite_line(event.line.text)
        print()


default_input, _ = sd.default.device
print("Available input devices (* = host default):")
for i, info in enumerate(sd.query_devices()):
    if info["max_input_channels"] > 0:
        marker = "*" if i == default_input else " "
        print(f"  {marker} [{i}] {info['name']} ({info['max_input_channels']} ch)")
print(f"Using device: {'host default' if MIC_DEVICE is None else MIC_DEVICE}\n")

print(f"Downloading/locating Moonshine model for language={LANGUAGE!r}...")
model_path, model_arch = get_model_for_language(LANGUAGE, MODEL_ARCH)
print(f"Model path: {model_path}")
print(f"Model arch: {model_arch}")

transcriber = MicTranscriber(
    model_path=model_path, model_arch=model_arch, device=MIC_DEVICE
)
transcriber.add_listener(TerminalListener())

print("Listening to the microphone, press Ctrl+C to stop...\n", file=sys.stderr)
transcriber.start()
try:
    while True:
        time.sleep(0.1)
except KeyboardInterrupt:
    print("\nStopping...")
finally:
    transcriber.stop()
    transcriber.close()
