from named_pipes.interfaces.interface import ArgSpec, CommandSpec, EventSpec, Interface

BASE = Interface(
    name="base",
    description="Built-in commands available on every ToolServer.",
    commands=[
        CommandSpec(name="get_config", description="Request the server's current configuration."),
        CommandSpec(name="get_description", description="Request the one-line description of the tool."),
        CommandSpec(name="get_help", description="Request the full help text."),
        CommandSpec(
            name="get_interface",
            description="Request the full Interface definition for a named interface the server implements.",
            args=[ArgSpec(name="name", description="Interface name to retrieve.", required=False, default="base")],
        ),
        CommandSpec(name="get_state", description="Request the current server state."),
        CommandSpec(name="list_interfaces", description="Request the list of interfaces the server implements."),
        CommandSpec(name="ping", description="Health check — server responds with a pong event."),
        CommandSpec(name="stop", description="Shut the server down gracefully."),
    ],
    events=[
        EventSpec(
            name="config",
            description="Response to get_config.",
            fields=[ArgSpec(name="config", description="Configuration dict.", type="dict")],
        ),
        EventSpec(
            name="description",
            description="Response to get_description.",
            fields=[ArgSpec(name="description", description="One-line description string.")],
        ),
        EventSpec(
            name="help",
            description="Response to get_help.",
            fields=[ArgSpec(name="text", description="Full help text.")],
        ),
        EventSpec(
            name="interfaces",
            description="Response to list_interfaces.",
            fields=[ArgSpec(name="interfaces", description="List of interface names the server implements.", type="list")],
        ),
        EventSpec(name="pong", description="Response to ping."),
        EventSpec(
            name="state",
            description="Response to get_state.",
            fields=[ArgSpec(name="state", description="Current state value.")],
        ),
        EventSpec(
            name="state_changed",
            description="Broadcast when the server state changes.",
            fields=[ArgSpec(name="state", description="New state value.")],
        ),
    ],
)
