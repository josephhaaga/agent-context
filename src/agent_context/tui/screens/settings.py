"""TUI settings screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Label


class SettingsScreen(Screen):
    """Placeholder settings screen — edit config.yaml directly for now."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label(
            "\n  Settings are managed via the config file.\n\n"
            "  Run:  agent-context config edit\n"
            "  or:   agent-context config show\n",
            id="hint",
        )
        yield Footer()
