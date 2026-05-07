"""© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en
"""

from named_pipes.interfaces.interface import ArgSpec, EventSpec, Interface

STT = Interface(
    name="stt",
    description="Speech-to-text — streams transcription tokens from the microphone over a named pipe. Producer-only; no custom commands.",
    events=[
        EventSpec(name="speech_end", description="Broadcast when speech offset is detected."),
        EventSpec(name="speech_start", description="Broadcast when speech onset is detected."),
        EventSpec(
            name="token",
            description="A transcribed token from the current utterance.",
            fields=[ArgSpec(name="text", description="Token text.")],
        ),
    ],
)
