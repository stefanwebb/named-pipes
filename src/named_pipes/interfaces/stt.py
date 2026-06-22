"""© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en
"""

from named_pipes.interfaces.interface import ArgSpec, CommandSpec, EventSpec, Interface

STT = Interface(
    name="stt",
    description="Speech-to-text — streams transcription tokens from the microphone over a named pipe.",
    commands=[
        CommandSpec(
            name="start", description="Start or resume listening on the microphone."
        ),
        CommandSpec(
            name="pause",
            description="Stop listening; finish transcribing audio already received.",
        ),
        CommandSpec(
            name="list_devices", description="List available audio input devices."
        ),
        CommandSpec(
            name="get_device",
            description="Get the audio input device used by the current stream.",
        ),
        CommandSpec(
            name="set_device",
            description="Set the audio input device used by the current stream.",
            args=[
                ArgSpec(
                    name="device",
                    description="Identifier of the audio input device to use.",
                )
            ],
        ),
    ],
    events=[
        EventSpec(
            name="speech_end", description="Broadcast when speech offset is detected."
        ),
        EventSpec(
            name="speech_start", description="Broadcast when speech onset is detected."
        ),
        EventSpec(
            name="speech",
            description="Broadcast when the current speech utterance has an update.",
            fields=[
                ArgSpec(
                    name="text",
                    description="Updated transcription of the current utterance.",
                ),
                ArgSpec(
                    name="words",
                    type="list",
                    required=False,
                    description=(
                        "Per-word timestamps when forced alignment is enabled: list of "
                        "{word, start, end} with absolute Unix epoch seconds (ms precision)."
                    ),
                ),
            ],
        ),
        EventSpec(
            name="token",
            description="A transcribed token from the current utterance.",
            fields=[ArgSpec(name="text", description="Token text.")],
        ),
        EventSpec(
            name="devices",
            description="Response to list_devices.",
            fields=[
                ArgSpec(
                    name="devices",
                    description="Available audio input devices.",
                    type="list",
                )
            ],
        ),
        EventSpec(
            name="device",
            description="Response to get_device or set_device.",
            fields=[
                ArgSpec(
                    name="device",
                    description="Identifier of the audio input device in use.",
                )
            ],
        ),
    ],
)
