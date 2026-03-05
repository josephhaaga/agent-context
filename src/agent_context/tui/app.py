"""Main TUI application."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header

from agent_context.config.models import AppConfig
from agent_context.tui.screens.search import SearchScreen
from agent_context.tui.screens.settings import SettingsScreen


class AgentContextApp(App):
    """Textual TUI for agent-context."""

    TITLE = "agent-context"
    SUB_TITLE = "Enterprise documentation search"

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+s", "push_screen('settings')", "Settings"),
    ]

    SCREENS = {
        "settings": SettingsScreen,
    }

    def __init__(self, config: AppConfig, **kwargs) -> None:
        super().__init__(**kwargs)
        self._config = config

    def on_mount(self) -> None:
        self.push_screen(SearchScreen(self._config))
