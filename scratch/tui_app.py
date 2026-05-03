import json

from named_pipes.chat.server import Backend
from named_pipes.registry import Backend as RegBackend, ServerType, default_for_backend, models_for_backend
from named_pipes.system import get_system_info, get_tools_info, ToolInfo
from textual.app import App, ComposeResult, on
from textual.binding import Binding
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    Rule,
    Select,
    Switch,
    TabbedContent,
    TabPane,
    TextArea,
)
from textual.containers import Horizontal, Vertical


def _reg_backend(backend: Backend) -> RegBackend | None:
    try:
        return RegBackend[backend.name]
    except KeyError:
        return None


def _model_options(backend: Backend) -> list[tuple[str, str]]:
    rb = _reg_backend(backend)
    if rb is None:
        return []
    return [(m.hub_id, m.hub_id) for m in models_for_backend(ServerType.CHAT, rb)]


def _default_model(backend: Backend) -> str | None:
    rb = _reg_backend(backend)
    if rb is None:
        return None
    entry = default_for_backend(ServerType.CHAT, rb)
    return entry.hub_id if entry else None


def _tools_str(tools: list[ToolInfo]) -> str:
    if not tools:
        return "  no tools found"
    lines = []
    for t in tools:
        status = "running" if t.running else "orphaned"
        desc = f"  {t.description}" if t.description else ""
        lines.append(f"  {t.name:<20} [{status}]{desc}")
    return "\n".join(lines)



class TuiApp(App):
    TITLE = "Named Pipes for Agentic Tools"

    CSS = """
    .field-row {
        height: auto;
        margin-bottom: 1;
        align: left middle;
    }
    .field-row Label {
        width: 20;
        padding-right: 1;
    }
    .field-row Input, .field-row Select {
        width: 1fr;
    }
    #backend-kwargs {
        height: 5;
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("1", "switch_tab('tab-system')", "System"),
        Binding("2", "switch_tab('tab-launcher')", "Launcher"),
    ]

    def compose(self) -> ComposeResult:
        info = get_system_info()
        yield Header()
        with TabbedContent(initial="tab-system", id="outer-tabs"):
            with TabPane("System", id="tab-system"):
                with Vertical():
                    yield Label("[bold]Hardware[/bold]", markup=True)
                    yield Rule()
                    yield Label(info.hardware_str())
                    yield Label("")
                    yield Label("[bold]Libraries[/bold]", markup=True)
                    yield Rule()
                    yield Label(info.libraries_str())
                    yield Label("")
                    yield Label("[bold]Tools[/bold]", markup=True)
                    yield Rule()
                    yield Label("scanning...", id="tools-content")
            with TabPane("Launcher", id="tab-launcher"):
                with TabbedContent(initial="launcher-chat"):
                    with TabPane("Chat", id="launcher-chat"):
                        with Vertical():
                            with Horizontal(classes="field-row"):
                                yield Label("name:")
                                yield Input(value="chat", id="chat-name")
                            with Horizontal(classes="field-row"):
                                yield Label("model:")
                                yield Select(
                                    _model_options(Backend.TRANSFORMERS),
                                    value=_default_model(Backend.TRANSFORMERS),
                                    id="chat-model",
                                )
                            with Horizontal(classes="field-row"):
                                yield Label("backend:")
                                yield Select(
                                    [(b.value, b) for b in Backend],
                                    value=Backend.TRANSFORMERS,
                                    id="chat-backend",
                                )
                            with Horizontal(classes="field-row"):
                                yield Label("description:")
                                yield Input(value="LLM chat server over a named pipe.", id="chat-description")
                            with Horizontal(classes="field-row"):
                                yield Label("backend_kwargs:")
                                yield TextArea(
                                    json.dumps({"max_new_tokens": 256, "do_sample": False}, indent=2),
                                    id="backend-kwargs",
                                )
                            with Horizontal(classes="field-row"):
                                yield Label("verbose:")
                                yield Switch(value=False, id="chat-verbose")
                    with TabPane("Text-to-speech", id="launcher-tts"):
                        yield Label("Text-to-speech content goes here.")
                    with TabPane("Speech-to-text", id="launcher-stt"):
                        yield Label("Speech-to-text content goes here.")
        yield Footer()

    def _load_tools(self) -> None:
        tools = get_tools_info()
        self.call_from_thread(self._update_tools, tools)

    def _update_tools(self, tools: list[ToolInfo]) -> None:
        self.query_one("#tools-content", Label).update(_tools_str(tools))

    def on_mount(self) -> None:
        self._chat_backend: Backend = Backend.TRANSFORMERS
        self.run_worker(self._load_tools, thread=True)

    @on(Select.Changed, "#chat-backend")
    def on_chat_backend_changed(self, event: Select.Changed) -> None:
        backend: Backend = event.value
        options = _model_options(backend)
        if not options:
            self.notify(f"No models registered for {backend.value}", severity="error")
            self.query_one("#chat-backend", Select).value = self._chat_backend
            return
        self._chat_backend = backend
        model_select = self.query_one("#chat-model", Select)
        current = model_select.value
        model_select.set_options(options)
        if not any(v == current for _, v in options):
            model_select.value = _default_model(backend) or Select.BLANK

    def action_switch_tab(self, tab_id: str) -> None:
        self.query_one("#outer-tabs", TabbedContent).active = tab_id


if __name__ == "__main__":
    TuiApp().run()
