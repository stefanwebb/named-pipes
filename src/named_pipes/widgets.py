from textual.binding import Binding
from textual.widgets import TextArea


class AutoTextArea(TextArea):
    """TextArea that resizes its height to fit its content and blurs on Escape."""

    BINDINGS = [Binding("escape", "dismiss_input", "Dismiss textbox", key_display="esc")]

    def _fit_height(self) -> None:
        lines = self.text.count("\n") + 1
        self.styles.height = max(3, lines + 2)

    def on_mount(self) -> None:
        self._fit_height()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._fit_height()

    def action_dismiss_input(self) -> None:
        self.blur()
