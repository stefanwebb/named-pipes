"""© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en
"""

"""Streaming speech-to-text over a named pipe.

Exports are lazy so that importing lightweight submodules (e.g. ``alignment``)
does not pull in the Voxtral/MLX stack.
"""

__all__ = ["STTConfig", "STTServer"]


def __getattr__(name):
    if name in ("STTConfig", "STTServer"):
        from named_pipes.stt.server import STTConfig, STTServer

        return {"STTConfig": STTConfig, "STTServer": STTServer}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
