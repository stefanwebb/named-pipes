import json
import os
import subprocess
import sys
import threading

from rich.text import Text
from named_pipes.chat.server import Backend
from named_pipes.registry import Backend as RegBackend, ServerType, default_for_backend, models_for_backend
from named_pipes.system import get_system_info, _tool_name_from_path
from named_pipes.tool_client import ToolClient
from named_pipes.utils import _is_fifo_connected, scan_pipes
from textual.app import App, ComposeResult, on
from textual.binding import Binding
from textual.widgets import (
    Button,
    DataTable,
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
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message

TOOL_POLL_INTERVAL = 1.0


class _ToolsTable(DataTable):
    class RowClicked(Message):
        def __init__(self, row_key) -> None:
            super().__init__()
            self.row_key = row_key

    def on_click(self, event) -> None:
        if self.row_count == 0:
            return
        header_height = 1 if self.show_header else 0
        if event.y < header_height:
            return
        self.show_cursor = True
        self.call_after_refresh(self._post_row_clicked)

    def _post_row_clicked(self) -> None:
        try:
            row_key, _ = self.coordinate_to_cell_key(self.cursor_coordinate)
            self.post_message(self.RowClicked(row_key))
        except Exception:
            pass


class _ManagedClient:
    """Persistent ToolClient with cached description and one-shot ping/state polling."""

    def __init__(self, name: str):
        self.name = name
        self.description: str = ""
        self._client = ToolClient(name)
        self._pong_event = threading.Event()
        self._state_event = threading.Event()
        self._state_val: str = "unknown"

        @self._client.on("pong")
        def _(msg):
            self._pong_event.set()

        @self._client.on("state")
        def _(msg):
            self._state_val = msg.get("state", "unknown")
            self._state_event.set()

        @self._client.on("description")
        def _(msg):
            self.description = msg.get("description") or ""

        self._client.listen()
        self._client.subscribe()
        self._client.send_command("get_description")

    def poll(self) -> tuple[bool, str]:
        """Send ping + get_state; return (healthy, state). Blocks up to ~0.5 s each."""
        self._pong_event.clear()
        self._state_event.clear()
        self._client.send_command("ping")
        self._client.send_command("get_state")
        healthy = self._pong_event.wait(timeout=0.5)
        self._state_event.wait(timeout=0.5)
        return healthy, self._state_val

    def close(self) -> None:
        try:
            self._client.unsubscribe()
            self._client._close()
        except Exception:
            pass


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
        height: 10;
        width: 1fr;
    }
    .system-col {
        border: round $primary;
        padding: 1;
        margin: 1;
        overflow-y: auto;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("1", "switch_tab('tab-system')", "System"),
        Binding("2", "switch_tab('tab-launcher')", "Launcher"),
        Binding("3", "switch_tab('tab-messenger')", "Messenger"),
    ]

    def compose(self) -> ComposeResult:
        info = get_system_info()
        yield Header()
        with TabbedContent(initial="tab-system", id="outer-tabs"):
            with TabPane("System", id="tab-system"):
                with Horizontal():
                    with Vertical(classes="system-col") as left_col:
                        left_col.border_title = "Info"
                        yield Label("[bold]Hardware[/bold]", markup=True)
                        yield Rule()
                        yield Label(info.hardware_str())
                        yield Label("")
                        yield Label("[bold]Libraries[/bold]", markup=True)
                        yield Rule()
                        yield Label(info.libraries_str())
                    with Vertical(classes="system-col") as right_col:
                        right_col.border_title = "Tools"
                        yield _ToolsTable(id="tools-table", cursor_type="row", show_cursor=False)
            with TabPane("Launcher", id="tab-launcher"):
                with TabbedContent(initial="launcher-chat"):
                    with TabPane("Chat", id="launcher-chat"):
                        with VerticalScroll():
                            with Horizontal(classes="field-row"):
                                yield Label("name:")
                                yield Input(value="chat", id="chat-name")
                            with Horizontal(classes="field-row"):
                                yield Label("model:")
                                yield Select(
                                    _model_options(Backend.TRANSFORMERS),
                                    value=_default_model(Backend.TRANSFORMERS),
                                    allow_blank=False,
                                    id="chat-model",
                                )
                            with Horizontal(classes="field-row"):
                                yield Label("backend:")
                                yield Select(
                                    [(b.value, b) for b in Backend],
                                    value=Backend.TRANSFORMERS,
                                    allow_blank=False,
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
                            yield Button("Launch", id="chat-launch", variant="success")
                    with TabPane("Text-to-speech", id="launcher-tts"):
                        yield Label("Text-to-speech content goes here.")
                    with TabPane("Speech-to-text", id="launcher-stt"):
                        yield Label("Speech-to-text content goes here.")
            with TabPane("Messenger", id="tab-messenger"):
                with VerticalScroll():
                    with Horizontal(classes="field-row"):
                        yield Label("tool:")
                        yield Select(
                            [("(no tools running)", "")],
                            allow_blank=False,
                            disabled=True,
                            id="messenger-tool",
                        )
        yield Footer()

    def on_mount(self) -> None:
        self._chat_backend: Backend = Backend.TRANSFORMERS
        self._managed_clients: dict[str, _ManagedClient] = {}
        self._table_rows: set[str] = set()
        self._stop_polling = threading.Event()

        table = self.query_one("#tools-table", DataTable)
        table.add_column("", key="health", width=2)
        table.add_column("Name", key="name")
        table.add_column("State", key="state")
        table.add_column("Description", key="description")

        self.run_worker(self._poll_loop, thread=True)

    def on_unmount(self) -> None:
        self._stop_polling.set()
        for mc in self._managed_clients.values():
            mc.close()

    def _poll_loop(self) -> None:
        while True:
            self._do_poll()
            if self._stop_polling.wait(timeout=TOOL_POLL_INTERVAL):
                break

    def _do_poll(self) -> None:
        pipe_data = scan_pipes("/tmp", with_pids=False)

        connected_names: set[str] = set()
        for entry in pipe_data.get("connected", []):
            name = _tool_name_from_path(entry["path"])
            if name:
                connected_names.add(name)

        orphaned_names: set[str] = set()
        for path in pipe_data.get("orphaned", []):
            name = _tool_name_from_path(path)
            if name:
                orphaned_names.add(name)

        # close connections for tools that are no longer connected
        for name in set(self._managed_clients) - connected_names:
            self._managed_clients.pop(name).close()

        # open connections for newly discovered tools
        for name in connected_names - set(self._managed_clients):
            try:
                self._managed_clients[name] = _ManagedClient(name)
            except Exception:
                pass

        statuses: list[tuple[str, bool, str, str]] = []

        for name, mc in list(self._managed_clients.items()):
            try:
                healthy, state = mc.poll()
            except Exception:
                healthy, state = False, "error"
            statuses.append((name, healthy, state, mc.description))

        for name in sorted(orphaned_names):
            statuses.append((name, False, "orphaned", ""))

        self.call_from_thread(self._refresh_tool_table, statuses)

    def _refresh_tool_table(self, statuses: list[tuple[str, bool, str, str]]) -> None:
        table = self.query_one("#tools-table", DataTable)
        new_names = {s[0] for s in statuses}

        for name in self._table_rows - new_names:
            table.remove_row(name)
        self._table_rows &= new_names

        for name, healthy, state, description in statuses:
            health = Text("●", style="green bold") if healthy else Text("●", style="red bold")
            if name in self._table_rows:
                table.update_cell(name, "health", health)
                table.update_cell(name, "state", state)
                table.update_cell(name, "description", description)
            else:
                table.add_row(health, name, state, description, key=name)
                self._table_rows.add(name)

        running_names = [name for name, healthy, _, _ in statuses if healthy]
        messenger_select = self.query_one("#messenger-tool", Select)
        if running_names:
            options = [(n, n) for n in running_names]
            current_val = messenger_select.value
            messenger_select.set_options(options)
            messenger_select.value = (
                current_val if any(v == current_val for _, v in options) else running_names[0]
            )
            messenger_select.disabled = False
        else:
            messenger_select.disabled = True

    @on(_ToolsTable.RowClicked)
    def on_tools_row_clicked(self, event: _ToolsTable.RowClicked) -> None:
        name = str(event.row_key.value)
        messenger_select = self.query_one("#messenger-tool", Select)
        if name in self._managed_clients:
            messenger_select.value = name
        self.query_one("#outer-tabs", TabbedContent).active = "tab-messenger"
        self.query_one("#tools-table", _ToolsTable).show_cursor = False

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

    @on(Button.Pressed, "#chat-launch")
    def on_chat_launch(self) -> None:
        name = self.query_one("#chat-name", Input).value.strip()
        pipe_path = f"/tmp/tool-{name}"
        if os.path.exists(pipe_path) and _is_fifo_connected(pipe_path):
            self.notify(f"Tool '{name}' is already running", severity="error")
            return

        backend = self.query_one("#chat-backend", Select).value
        model = self.query_one("#chat-model", Select).value
        description = self.query_one("#chat-description", Input).value.strip()
        verbose = self.query_one("#chat-verbose", Switch).value

        try:
            backend_kwargs = json.loads(self.query_one("#backend-kwargs", TextArea).text)
        except json.JSONDecodeError:
            self.notify("backend_kwargs is not valid JSON", severity="error")
            return

        config = {
            "name": name,
            "model": model,
            "backend": backend.value,
            "description": description,
            "backend_kwargs": backend_kwargs,
            "verbose": verbose,
        }
        log_path = f"/tmp/tool-{name}.log"
        log = open(log_path, "w")
        subprocess.Popen(
            [sys.executable, "-m", "named_pipes.chat.launch", json.dumps(config)],
            start_new_session=True,
            stdout=log,
            stderr=log,
        )
        self.notify(f"Launched chat server '{name}' — log: {log_path}")

    def action_switch_tab(self, tab_id: str) -> None:
        self.query_one("#outer-tabs", TabbedContent).active = tab_id


if __name__ == "__main__":
    TuiApp().run()
