from pydantic import BaseModel, Field


class ArgSpec(BaseModel):
    """A single command argument or event field."""
    name: str
    description: str
    type: str = "str"
    required: bool = True


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
