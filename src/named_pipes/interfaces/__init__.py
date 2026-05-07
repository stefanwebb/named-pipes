"""© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en
"""

from named_pipes.interfaces.interface import ArgSpec, CommandSpec, EventSpec, Interface
from named_pipes.interfaces.base import BASE
from named_pipes.interfaces.chat import CHAT
from named_pipes.interfaces.tts import TTS
from named_pipes.interfaces.stt import STT

__all__ = [
    "ArgSpec",
    "CommandSpec",
    "EventSpec",
    "Interface",
    "BASE",
    "CHAT",
    "TTS",
    "STT",
]
