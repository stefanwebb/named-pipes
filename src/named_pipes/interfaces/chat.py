from named_pipes.interfaces.interface import ArgSpec, CommandSpec, EventSpec, Interface

CHAT = Interface(
    name="chat",
    description="LLM chat — streaming and blocking inference over a named pipe.",
    commands=[
        CommandSpec(
            name="chat",
            description="Stream an LLM response; emits chunk events followed by a done event.",
            args=[
                ArgSpec(
                    name="messages",
                    description='List of {"role": ..., "content": ...} message dicts.',
                    type="list",
                    default='[{"role":"user", "content":"Hello!"}]',
                )
            ],
        ),
        CommandSpec(
            name="chat_blocking",
            description="Run inference synchronously and return a single reply event.",
            args=[
                ArgSpec(
                    name="messages",
                    description='List of {"role": ..., "content": ...} message dicts.',
                    type="list",
                    default='[{"role":"user", "content":"Hello!"}]',
                )
            ],
        ),
    ],
    events=[
        EventSpec(
            name="chunk",
            description="A streamed token from an in-progress response.",
            fields=[ArgSpec(name="text", description="Token text.")],
        ),
        EventSpec(name="done", description="Signals the end of a streaming response."),
        EventSpec(
            name="reply",
            description="Complete reply returned by chat_blocking.",
            fields=[ArgSpec(name="text", description="Full reply text.")],
        ),
    ],
)
