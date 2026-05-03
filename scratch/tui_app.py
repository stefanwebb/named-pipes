from named_pipes.system import get_system_info
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Label, Rule, TabbedContent, TabPane
from textual.containers import Vertical


class TuiApp(App):
    TITLE = "Named Pipes for Agentic Tools"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("1", "switch_tab('tab-system')", "System"),
        Binding("2", "switch_tab('tab-two')", "Tab 2"),
    ]

    def compose(self) -> ComposeResult:
        info = get_system_info()
        yield Header()
        with TabbedContent(initial="tab-system"):
            with TabPane("System", id="tab-system"):
                with Vertical():
                    yield Label("[bold]Hardware[/bold]", markup=True)
                    yield Rule()
                    yield Label(info.hardware_str())
                    yield Label("")
                    yield Label("[bold]Libraries[/bold]", markup=True)
                    yield Rule()
                    yield Label(info.libraries_str())
            with TabPane("Tab Two", id="tab-two"):
                yield Label("Welcome to Tab Two!\n\nThis is the second tab.")
        yield Footer()

    def action_switch_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id


if __name__ == "__main__":
    TuiApp().run()
