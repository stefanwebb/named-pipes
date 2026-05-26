"""© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en
"""

import json
import os
import subprocess
import sys
import threading
import types

from rich.segment import Segment
from rich.text import Text
from named_pipes.chat.server import Backend, ChatConfig
from named_pipes.tts.server import TTSConfig
from named_pipes.stt.server import STTConfig
from named_pipes.registry import Backend as RegBackend, ServerType, default_for_backend, models_for_backend
from named_pipes.system import get_system_info, _tool_name_from_path
from named_pipes.tools.client import ToolClient
from named_pipes.utils import _is_fifo_connected, scan_pipes
from named_pipes.app.widgets import AutoTextArea
from textual.app import App, ComposeResult, on
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
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

_MESSENGER_COMMANDS = ["get_state", "get_description", "get_help", "get_config", "list_interfaces", "get_interface", "stop"]


class _Input(Input):
    BINDINGS = [Binding("escape", "dismiss_input", "Dismiss textbox", key_display="esc")]

    def action_dismiss_input(self) -> None:
        self.blur()


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
        self.interfaces: list[str] = []
        self.on_event: callable | None = None
        self.on_interface_def: callable | None = None
        self._client = ToolClient(name)
        self._pong_event = threading.Event()
        self._state_val: str = "unknown"
        self._discovering = True
        self._pending_ifaces = 0
        self._suppress_pong = False

        @self._client.on("pong")
        def _(msg):
            self._pong_event.set()

        @self._client.on("state")
        def _(msg):
            self._state_val = msg.get("state", "unknown")

        @self._client.on("state_changed")
        def _(msg):
            self._state_val = msg.get("state", self._state_val)

        @self._client.on("description")
        def _(msg):
            self.description = msg.get("description") or ""

        @self._client.on("interfaces")
        def _(msg):
            self.interfaces = msg.get("interfaces", [])
            if not self._discovering:
                return
            self._pending_ifaces = len(self.interfaces)
            if self._pending_ifaces == 0:
                self._discovering = False
            for iface_name in self.interfaces:
                self._client.send_command("get_interface", name=iface_name)

        @self._client.on("interface")
        def _(msg):
            self._pending_ifaces = max(0, self._pending_ifaces - 1)
            if self._pending_ifaces == 0:
                self._discovering = False
            defn = msg.get("interface")
            iface_name = defn.get("name") if isinstance(defn, dict) else None
            if iface_name and defn:
                cb = self.on_interface_def
                if cb is not None:
                    cb(iface_name, defn)

        # Patch msg_handler_fn to forward all non-internal events to on_event
        _orig = self._client.__class__.msg_handler_fn
        _mc = self

        def _patched(client_self, msg, pid):
            was_discovering = _mc._discovering
            _orig(client_self, msg, pid)
            cb = _mc.on_event
            event = msg.get("event")
            if cb is not None and event not in ("subscribed",):
                if event == "interface" and was_discovering:
                    return
                if event == "pong" and _mc._suppress_pong:
                    return
                cb(msg)

        self._client.msg_handler_fn = types.MethodType(_patched, self._client)

        self._client.listen()
        self._client.subscribe()
        self._client.send_command("get_description")
        self._client.send_command("get_state")
        self._client.send_command("list_interfaces")

    def poll(self) -> tuple[bool, str]:
        """Send ping; return (healthy, state). State is maintained via events."""
        self._pong_event.clear()
        self._suppress_pong = True
        self._client.send_command("ping")
        healthy = self._pong_event.wait(timeout=0.5)
        self._suppress_pong = False
        return healthy, self._state_val

    def send_command(self, cmd: str, **kwargs) -> None:
        self._client.send_command(cmd, **kwargs)

    def close(self) -> None:
        try:
            self._client.unsubscribe()
            self._client._close()
        except Exception:
            pass


class _VerticalSeparator(Widget):
    DEFAULT_CSS = """
    _VerticalSeparator {
        width: 1;
        height: 100%;
        margin: 0;
        color: $primary;
    }
    """

    def __init__(self, *panel_ids: str):
        super().__init__()
        self._panel_ids = panel_ids

    def render_line(self, y: int) -> Strip:
        style = self.rich_style
        char = "│"
        try:
            my_y = self.region.y
            junctions: set[int] = set()
            for pid in self._panel_ids:
                r = self.app.query_one(f"#{pid}").region
                junctions.add(r.y - my_y)
                junctions.add(r.y + r.height - 1 - my_y)
            if y in junctions:
                char = "┼"
        except Exception:
            pass
        return Strip([Segment(char, style)])


class LaunchModal(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss", "Close"), Binding("l", "dismiss", "Close")]

    CSS = """
    LaunchModal {
        align: center middle;
    }
    LaunchModal > Vertical {
        width: 72;
        height: 85%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    """

    def on_mount(self) -> None:
        self._chat_backend: Backend = Backend.TRANSFORMERS

    @on(Select.Changed, "#chat-backend")
    def on_chat_backend_changed(self, event: Select.Changed) -> None:
        backend: Backend = event.value
        options = _model_options(backend)
        if not options:
            self.app.notify(f"No models registered for {backend.value}", severity="error")
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
            self.app.notify(f"Tool '{name}' is already running", severity="error")
            return
        backend = self.query_one("#chat-backend", Select).value
        model = self.query_one("#chat-model", Select).value
        description = self.query_one("#chat-description", Input).value.strip()
        verbose = self.query_one("#chat-verbose", Switch).value
        try:
            backend_kwargs = json.loads(self.query_one("#backend-kwargs", AutoTextArea).text)
        except json.JSONDecodeError:
            self.app.notify("backend_kwargs is not valid JSON", severity="error")
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
        self.app.notify(f"Launched chat server '{name}' — log: {log_path}")

    @on(Button.Pressed, "#tts-launch")
    def on_tts_launch(self) -> None:
        name = self.query_one("#tts-name", Input).value.strip()
        pipe_path = f"/tmp/tool-{name}"
        if os.path.exists(pipe_path) and _is_fifo_connected(pipe_path):
            self.app.notify(f"Tool '{name}' is already running", severity="error")
            return
        try:
            sample_rate = int(self.query_one("#tts-sample-rate", Input).value.strip())
            blocksize = int(self.query_one("#tts-blocksize", Input).value.strip())
        except ValueError:
            self.app.notify("sample_rate and blocksize must be integers", severity="error")
            return
        config = {
            "name": name,
            "description": self.query_one("#tts-description", Input).value.strip(),
            "model_id": self.query_one("#tts-model-id", Input).value.strip(),
            "voice": self.query_one("#tts-voice", Input).value.strip(),
            "sample_rate": sample_rate,
            "blocksize": blocksize,
            "verbose": self.query_one("#tts-verbose", Switch).value,
        }
        log_path = f"/tmp/tool-{name}.log"
        log = open(log_path, "w")
        subprocess.Popen(
            [sys.executable, "-m", "named_pipes.tts.launch", json.dumps(config)],
            start_new_session=True,
            stdout=log,
            stderr=log,
        )
        self.app.notify(f"Launched TTS server '{name}' — log: {log_path}")

    @on(Button.Pressed, "#stt-launch")
    def on_stt_launch(self) -> None:
        name = self.query_one("#stt-name", Input).value.strip()
        pipe_path = f"/tmp/tool-{name}"
        if os.path.exists(pipe_path) and _is_fifo_connected(pipe_path):
            self.app.notify(f"Tool '{name}' is already running", severity="error")
            return
        try:
            temperature = float(self.query_one("#stt-temperature", Input).value.strip())
            vad_onset = int(self.query_one("#stt-vad-onset", Input).value.strip())
            vad_offset = int(self.query_one("#stt-vad-offset", Input).value.strip())
        except ValueError:
            self.app.notify("temperature must be a float; vad_onset and vad_offset must be integers", severity="error")
            return
        config = {
            "name": name,
            "description": self.query_one("#stt-description", Input).value.strip(),
            "model_path": self.query_one("#stt-model-path", Input).value.strip(),
            "temperature": temperature,
            "vad_onset": vad_onset,
            "vad_offset": vad_offset,
            "verbose": self.query_one("#stt-verbose", Switch).value,
        }
        log_path = f"/tmp/tool-{name}.log"
        log = open(log_path, "w")
        subprocess.Popen(
            [sys.executable, "-m", "named_pipes.stt.launch", json.dumps(config)],
            start_new_session=True,
            stdout=log,
            stderr=log,
        )
        self.app.notify(f"Launched STT server '{name}' — log: {log_path}")

    def compose(self) -> ComposeResult:
        with Vertical():
            with TabbedContent(initial="launcher-chat"):
                with TabPane("Chat", id="launcher-chat"):
                    with VerticalScroll():
                        with Horizontal(classes="field-row"):
                            yield Label("name:")
                            yield _Input(value=ChatConfig.model_fields["name"].default, id="chat-name")
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
                                value=ChatConfig.model_fields["backend"].default,
                                allow_blank=False,
                                id="chat-backend",
                            )
                        with Horizontal(classes="field-row"):
                            yield Label("description:")
                            yield _Input(value=ChatConfig.model_fields["description"].default, id="chat-description")
                        with Horizontal(classes="field-row"):
                            yield Label("backend_kwargs:")
                            yield AutoTextArea(
                                json.dumps(ChatConfig.model_fields["backend_kwargs"].default, indent=2),
                                id="backend-kwargs",
                            )
                        with Horizontal(classes="field-row"):
                            yield Label("verbose:")
                            yield Switch(value=ChatConfig.model_fields["verbose"].default, id="chat-verbose")
                        yield Button("Launch", id="chat-launch", variant="success")
                with TabPane("Text-to-speech", id="launcher-tts"):
                    with VerticalScroll():
                        with Horizontal(classes="field-row"):
                            yield Label("name:")
                            yield _Input(value=TTSConfig.model_fields["name"].default, id="tts-name")
                        with Horizontal(classes="field-row"):
                            yield Label("description:")
                            yield _Input(value=TTSConfig.model_fields["description"].default, id="tts-description")
                        with Horizontal(classes="field-row"):
                            yield Label("model_id:")
                            yield _Input(value=TTSConfig.model_fields["model_id"].default, id="tts-model-id")
                        with Horizontal(classes="field-row"):
                            yield Label("voice:")
                            yield _Input(value=TTSConfig.model_fields["voice"].default, id="tts-voice")
                        with Horizontal(classes="field-row"):
                            yield Label("sample_rate:")
                            yield _Input(value=str(TTSConfig.model_fields["sample_rate"].default), id="tts-sample-rate")
                        with Horizontal(classes="field-row"):
                            yield Label("blocksize:")
                            yield _Input(value=str(TTSConfig.model_fields["blocksize"].default), id="tts-blocksize")
                        with Horizontal(classes="field-row"):
                            yield Label("verbose:")
                            yield Switch(value=TTSConfig.model_fields["verbose"].default, id="tts-verbose")
                        yield Button("Launch", id="tts-launch", variant="success")
                with TabPane("Speech-to-text", id="launcher-stt"):
                    with VerticalScroll():
                        with Horizontal(classes="field-row"):
                            yield Label("name:")
                            yield _Input(value=STTConfig.model_fields["name"].default, id="stt-name")
                        with Horizontal(classes="field-row"):
                            yield Label("description:")
                            yield _Input(value=STTConfig.model_fields["description"].default, id="stt-description")
                        with Horizontal(classes="field-row"):
                            yield Label("model_path:")
                            yield _Input(value=STTConfig.model_fields["model_path"].default, id="stt-model-path")
                        with Horizontal(classes="field-row"):
                            yield Label("temperature:")
                            yield _Input(value=str(STTConfig.model_fields["temperature"].default), id="stt-temperature")
                        with Horizontal(classes="field-row"):
                            yield Label("vad_onset:")
                            yield _Input(value=str(STTConfig.model_fields["vad_onset"].default), id="stt-vad-onset")
                        with Horizontal(classes="field-row"):
                            yield Label("vad_offset:")
                            yield _Input(value=str(STTConfig.model_fields["vad_offset"].default), id="stt-vad-offset")
                        with Horizontal(classes="field-row"):
                            yield Label("verbose:")
                            yield Switch(value=STTConfig.model_fields["verbose"].default, id="stt-verbose")
                        yield Button("Launch", id="stt-launch", variant="success")


class InfoModal(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss", "Close"), Binding("i", "dismiss", "Close")]

    CSS = """
    InfoModal {
        align: center middle;
    }
    InfoModal > Vertical {
        width: 60;
        height: auto;
        max-height: 80%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    """

    def __init__(self, info):
        super().__init__()
        self._info = info

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[bold]Hardware[/bold]", markup=True)
            yield Rule()
            yield Label(self._info.hardware_str())
            yield Label("")
            yield Label("[bold]Libraries[/bold]", markup=True)
            yield Rule()
            yield Label(self._info.libraries_str())


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
    .field-row Input, .field-row Select, .field-row AutoTextArea {
        width: 1fr;
    }
    .system-col {
        border: round $primary;
        padding: 1;
        margin: 1;
        overflow-y: auto;
    }
    #messenger-args {
        height: auto;
    }
    #tools-panel {
        width: 1fr;
        height: 100%;
        margin-right: 0;
        border-right: none;
        border-left: none;
    }
    .right-split {
        width: 2fr;
        height: 100%;
    }
    .right-split .system-col {
        height: 1fr;
        border-left: none;
        border-right: none;
        margin-left: 0;
    }
    .output-col {
        border: round $primary;
        padding: 1;
        margin: 1;
        overflow-y: auto;
        height: 2fr;
    }
    .right-split .output-col {
        border-left: none;
        border-right: none;
        margin-left: 0;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("l", "show_launcher", "Launch"),
        Binding("i", "show_info", "Info"),
    ]

    def compose(self) -> ComposeResult:
        self._system_info = get_system_info()
        yield Header()
        with Horizontal():
            with Vertical(classes="system-col", id="tools-panel") as tools_panel:
                tools_panel.border_title = "Tools"
                yield _ToolsTable(id="tools-table", cursor_type="row", show_cursor=False)
            yield _VerticalSeparator("commands-panel", "stdout-panel")
            with Vertical(classes="right-split"):
                with Vertical(classes="system-col", id="commands-panel") as commands_panel:
                    commands_panel.border_title = "Commands"
                    yield Label("No tools running.", id="messenger-empty")
                    with Vertical(id="messenger-controls"):
                        with Horizontal(classes="field-row"):
                            yield Label("tool:")
                            yield Select(
                                [("", "")],
                                allow_blank=False,
                                id="messenger-tool",
                            )
                        with Horizontal(classes="field-row"):
                            yield Label("command:")
                            yield Select(
                                [(c, c) for c in _MESSENGER_COMMANDS],
                                allow_blank=False,
                                id="messenger-cmd",
                            )
                        with Vertical(id="messenger-args"):
                            pass
                        yield Button("Send", id="messenger-send", variant="primary")
                with Vertical(classes="output-col", id="stdout-panel") as stdout_panel:
                    stdout_panel.border_title = "stdout"
                    yield RichLog(id="tools-stdout", markup=False, highlight=False, max_lines=1000)
        yield Footer()

    _TABLE_IDS = ["tools-table"]

    def on_mount(self) -> None:
        self._managed_clients: dict[str, _ManagedClient] = {}
        self._table_rows: dict[str, set[str]] = {tid: set() for tid in self._TABLE_IDS}
        self._stop_polling = threading.Event()
        self._stop_log_watch = threading.Event()
        self._active_messenger_tool: str | None = None
        self._active_messenger_cmd: str | None = None
        self._interfaces: dict[str, dict] = {}
        self._arg_cache: dict[str, dict[str, dict[str, str]]] = {}
        self._watched_tool: str | None = None

        for tid in self._TABLE_IDS:
            table = self.query_one(f"#{tid}", _ToolsTable)
            table.add_column("", key="health", width=14)
            table.add_column("Name", key="name")
            table.add_column("Description", key="description")

        self.query_one("#messenger-empty", Label).display = True
        self.query_one("#messenger-controls", Vertical).display = False

        self.run_worker(self._poll_loop, thread=True)

    def on_unmount(self) -> None:
        if hasattr(self, "_stop_polling"):
            self._stop_polling.set()
        if hasattr(self, "_stop_log_watch"):
            self._stop_log_watch.set()
        for mc in getattr(self, "_managed_clients", {}).values():
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
                mc = _ManagedClient(name)
                mc.on_interface_def = self._on_interface_def
                if name == self._active_messenger_tool:
                    mc.on_event = self._make_event_callback()
                self._managed_clients[name] = mc
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
        new_names = {s[0] for s in statuses}

        for tid in self._TABLE_IDS:
            table = self.query_one(f"#{tid}", _ToolsTable)
            rows = self._table_rows[tid]

            for name in rows - new_names:
                table.remove_row(name)
            rows &= new_names

            for name, healthy, state, description in statuses:
                if not healthy or state == "error":
                    style = "red bold"
                elif state == "idle":
                    style = "grey50 bold"
                else:
                    style = "green bold"
                health = Text(f"● {state}", style=style)
                if name in rows:
                    table.update_cell(name, "health", health)
                    table.update_cell(name, "description", description)
                else:
                    table.add_row(health, name, description, key=name)
                    rows.add(name)

        has_any = bool(statuses)
        for tid in self._TABLE_IDS:
            self.query_one(f"#{tid}", _ToolsTable).display = has_any

        running_names = [name for name, healthy, _, _ in statuses if healthy]
        messenger_select = self.query_one("#messenger-tool", Select)
        has_tools = bool(running_names)
        self.query_one("#messenger-empty", Label).display = not has_tools
        self.query_one("#messenger-controls", Vertical).display = has_tools
        if not has_tools:
            self._stop_log_watch.set()
            self.query_one("#tools-stdout", RichLog).clear()
        if has_tools:
            options = [(n, n) for n in running_names]
            current_val = messenger_select.value
            new_val = current_val if any(v == current_val for _, v in options) else running_names[0]
            messenger_select.set_options(options)
            messenger_select.value = new_val
            if new_val != self._watched_tool or self._stop_log_watch.is_set():
                self._start_log_watcher(new_val)


    def _commands_for_tool(self, tool_name: str) -> list[dict]:
        mc = self._managed_clients.get(tool_name)
        if mc is None:
            return []
        commands = []
        for iface_name in mc.interfaces:
            iface_def = self._interfaces.get(iface_name)
            if iface_def:
                commands.extend(iface_def.get("commands", []))
        return commands

    def _command_spec(self, tool_name: str, cmd_name: str) -> dict | None:
        for cmd in self._commands_for_tool(tool_name):
            if cmd["name"] == cmd_name:
                return cmd
        return None

    def _refresh_messenger_commands(self, tool_name: str) -> None:
        commands = self._commands_for_tool(tool_name)
        cmd_select = self.query_one("#messenger-cmd", Select)
        if commands:
            options = sorted([(cmd["name"], cmd["name"]) for cmd in commands], key=lambda x: x[0])
        else:
            options = [(c, c) for c in sorted(_MESSENGER_COMMANDS)]
        current = str(cmd_select.value)
        cmd_select.set_options(options)
        cmd_select.value = current if any(v == current for _, v in options) else options[0][1]

    def _save_current_args(self) -> None:
        tool = self._active_messenger_tool
        cmd = self._active_messenger_cmd
        if not tool or not cmd:
            return
        cache = self._arg_cache.setdefault(tool, {}).setdefault(cmd, {})
        for ta in self.query_one("#messenger-args", Vertical).query(AutoTextArea):
            arg_name = ta.id.removeprefix("messenger-arg-")
            cache[arg_name] = ta.text

    def _refresh_messenger_args(self, tool_name: str, cmd_name: str) -> None:
        container = self.query_one("#messenger-args", Vertical)
        container.remove_children()
        spec = self._command_spec(tool_name, cmd_name)
        if not spec:
            return
        cached = self._arg_cache.get(tool_name, {}).get(cmd_name, {})
        for arg in spec.get("args", []):
            arg_name = arg["name"]
            if arg_name in cached:
                initial = cached[arg_name]
            else:
                initial = arg.get("default") or ""
            container.mount(
                Horizontal(
                    Label(f"{arg_name}:"),
                    AutoTextArea(
                        initial,
                        id=f"messenger-arg-{arg_name}",
                    ),
                    classes="field-row",
                )
            )

    @on(_ToolsTable.RowClicked)
    def on_tools_row_clicked(self, event: _ToolsTable.RowClicked) -> None:
        name = str(event.row_key.value)
        messenger_select = self.query_one("#messenger-tool", Select)
        if name in self._managed_clients:
            messenger_select.value = name
        for table in self.query(_ToolsTable):
            table.show_cursor = False

    def _make_event_callback(self) -> callable:
        def cb(msg: dict) -> None:
            self.call_from_thread(self._on_tool_event, msg)
        return cb

    def _on_interface_def(self, name: str, defn: dict) -> None:
        if name not in self._interfaces:
            self._interfaces[name] = defn
        elif defn != self._interfaces[name]:
            self.call_from_thread(
                self.notify,
                f"Interface '{name}' definition mismatch between tools",
                severity="warning",
            )
            return
        active = self._active_messenger_tool
        if active and active in self._managed_clients:
            mc = self._managed_clients[active]
            if name in mc.interfaces:
                self.call_from_thread(self._refresh_messenger_commands, active)

    def _on_tool_event(self, msg: dict) -> None:
        event = msg.get("event", "unknown")
        data = {k: v for k, v in msg.items() if k != "event"}
        text = f"{event}: {json.dumps(data)}" if data else event
        _MAX = 120
        if len(text) > _MAX:
            n_lines = text.count("\n") + text.count("\\n") + 1
            text = text[:_MAX] + f"… [{n_lines} lines]"
        self.notify(text, timeout=5)

    def _start_log_watcher(self, name: str) -> None:
        self._watched_tool = name
        self._stop_log_watch.set()
        self._stop_log_watch = threading.Event()
        stop = self._stop_log_watch
        log_path = f"/tmp/tool-{name}.log"
        log_widget = self.query_one("#tools-stdout", RichLog)
        log_widget.clear()

        def _watch() -> None:
            try:
                for _ in range(20):
                    if os.path.exists(log_path) or stop.is_set():
                        break
                    stop.wait(timeout=0.25)
                if stop.is_set():
                    return
                with open(log_path, "r") as f:
                    while not stop.is_set():
                        line = f.readline()
                        if line:
                            self.call_from_thread(log_widget.write, line.rstrip("\n"))
                        else:
                            stop.wait(timeout=0.05)
            except Exception:
                pass

        threading.Thread(target=_watch, daemon=True).start()

    @on(Select.Changed, "#messenger-tool")
    def on_messenger_tool_changed(self, event: Select.Changed) -> None:
        self._save_current_args()
        name = str(event.value)
        self._active_messenger_tool = name
        self._active_messenger_cmd = None  # prevent stale save during command refresh
        for n, mc in self._managed_clients.items():
            mc.on_event = self._make_event_callback() if n == name else None
        self.query_one("#messenger-send", Button).disabled = name not in self._managed_clients
        self._refresh_messenger_commands(name)
        if name != self._watched_tool:
            self._start_log_watcher(name)

    @on(Select.Changed, "#messenger-cmd")
    def on_messenger_cmd_changed(self, event: Select.Changed) -> None:
        self._save_current_args()
        self._active_messenger_cmd = str(event.value)
        tool = self._active_messenger_tool
        if tool:
            self._refresh_messenger_args(tool, str(event.value))

    @on(TextArea.Changed)
    def on_messenger_arg_changed(self, event: TextArea.Changed) -> None:
        ta = event.text_area
        if not (isinstance(ta, AutoTextArea) and ta.id and ta.id.startswith("messenger-arg-")):
            return
        tool = self._active_messenger_tool
        cmd = self._active_messenger_cmd
        if not tool or not cmd:
            return
        arg_name = ta.id.removeprefix("messenger-arg-")
        self._arg_cache.setdefault(tool, {}).setdefault(cmd, {})[arg_name] = ta.text

    @on(Button.Pressed, "#messenger-send")
    def on_messenger_send(self) -> None:
        self._save_current_args()
        tool = str(self.query_one("#messenger-tool", Select).value)
        cmd = str(self.query_one("#messenger-cmd", Select).value)
        mc = self._managed_clients.get(tool)
        if mc is None:
            self.notify(f"Tool '{tool}' not connected", severity="error")
            return
        spec = self._command_spec(tool, cmd)
        arg_types = {arg["name"]: arg.get("type", "str") for arg in (spec.get("args", []) if spec else [])}
        kwargs = {}
        for ta in self.query_one("#messenger-args", Vertical).query(AutoTextArea):
            if not ta.text:
                continue
            arg_name = ta.id.removeprefix("messenger-arg-")
            if arg_types.get(arg_name, "str") != "str":
                try:
                    kwargs[arg_name] = json.loads(ta.text)
                except json.JSONDecodeError:
                    self.notify(f"Argument '{arg_name}' must be valid JSON", severity="error")
                    return
            else:
                kwargs[arg_name] = ta.text
        mc.send_command(cmd, **kwargs)

    def action_show_launcher(self) -> None:
        self.push_screen(LaunchModal())

    def action_show_info(self) -> None:
        self.push_screen(InfoModal(self._system_info))


if __name__ == "__main__":
    TuiApp().run()
