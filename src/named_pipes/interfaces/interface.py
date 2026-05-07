"""© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en
"""

from pydantic import BaseModel, Field


class ArgSpec(BaseModel):
    """A single command argument or event field."""
    name: str
    description: str
    type: str = "str"
    required: bool = True
    default: str | None = None


class CommandSpec(BaseModel):
    """A command a server accepts."""
    name: str
    description: str
    args: list[ArgSpec] = Field(default_factory=list)


class EventSpec(BaseModel):
    """An event a server emits."""
    name: str
    description: str
    fields: list[ArgSpec] = Field(default_factory=list)


class Interface(BaseModel):
    """Describes a disjoint set of commands and events.

    A server typically implements multiple interfaces. For example, a chat
    server implements both BASE and CHAT.
    """
    name: str
    description: str
    commands: list[CommandSpec] = Field(default_factory=list)
    events: list[EventSpec] = Field(default_factory=list)
