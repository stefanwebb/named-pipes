"""© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en
"""

from named_pipes.interfaces.interface import ArgSpec, CommandSpec, EventSpec, Interface

TTS = Interface(
    name="tts",
    description="Text-to-speech — streams text tokens to an audio backend over a named pipe.",
    commands=[
        CommandSpec(name="flush", description="Flush any remaining buffered text to the speech queue."),
        CommandSpec(name="is_speaking", description="Request the current speaking status."),
        CommandSpec(
            name="text",
            description="Append a text token to the speech buffer.",
            args=[ArgSpec(name="data", description="Text token to enqueue for speech.")],
        ),
    ],
    events=[
        EventSpec(
            name="is_speaking",
            description="Response to is_speaking.",
            fields=[ArgSpec(name="speaking", description="True if audio is currently playing.", type="bool")],
        ),
        EventSpec(name="speech_start", description="Broadcast when audio playback begins."),
        EventSpec(name="speech_end", description="Broadcast when audio playback ends."),
    ],
)
