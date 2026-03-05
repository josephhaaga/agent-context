"""TUI search screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static


class ResultItem(ListItem):
    """A single search result row in the list."""

    def __init__(self, title: str, meta: str, doc_id: str) -> None:
        super().__init__()
        self._title = title
        self._meta = meta
        self.doc_id = doc_id

    def compose(self) -> ComposeResult:
        yield Static(self._title, classes="result-title")
        yield Static(self._meta, classes="result-meta")


class SearchScreen(Screen):
    """Main interactive search screen."""

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
        Binding("enter", "open_detail", "Open"),
        Binding("ctrl+r", "refresh", "Refresh index"),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }
    #search-input {
        dock: top;
        margin: 1 2;
    }
    #results {
        height: 1fr;
        margin: 0 2;
        border: solid $accent;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        margin: 0 2;
        color: $text-muted;
    }
    .result-title {
        text-style: bold;
        color: $text;
    }
    .result-meta {
        color: $text-muted;
        text-style: dim;
    }
    """

    def __init__(self, app_config, **kwargs):
        super().__init__(**kwargs)
        self._config = app_config
        self._results = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Input(placeholder="Search…", id="search-input")
        yield ListView(id="results")
        yield Label("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            return
        await self._do_search(query)

    async def _do_search(self, query: str) -> None:

        from agent_context.search.engine import search as hybrid_search  # noqa: PLC0415
        from agent_context.storage.database import Database  # noqa: PLC0415

        status = self.query_one("#status-bar", Label)
        status.update(f"Searching for '{query}'…")
        lv = self.query_one("#results", ListView)
        await lv.clear()

        try:
            async with Database(self._config.db_path) as db:
                results = await hybrid_search(
                    db,
                    query,
                    semantic=self._config.search.semantic,
                    keyword_weight=self._config.search.keyword_weight,
                    semantic_weight=self._config.search.semantic_weight,
                    model_name=self._config.search.model,
                    limit=self._config.search.default_limit,
                )
            self._results = results

            if not results:
                status.update("No results found.")
                return

            for r in results:
                doc = r.document
                meta_parts = [doc.source, doc.doc_type]
                if doc.updated_at:
                    meta_parts.append(str(doc.updated_at.date()))
                meta = "  ·  ".join(meta_parts) + f"  [{r.score:.2f}]"
                await lv.append(ResultItem(doc.title, meta, doc.id))

            status.update(f"{len(results)} results  (↑↓ navigate, Enter to open)")
        except Exception as exc:  # noqa: BLE001
            status.update(f"[red]Error:[/red] {exc}")

    def action_open_detail(self) -> None:
        lv = self.query_one("#results", ListView)
        if lv.highlighted_child is None:
            return
        item = lv.highlighted_child
        if not isinstance(item, ResultItem):
            return
        # Find the result
        result = next((r for r in self._results if r.document.id == item.doc_id), None)
        if result:
            from agent_context.tui.screens.detail import DetailScreen  # noqa: PLC0415

            self.app.push_screen(DetailScreen(result))

    def action_refresh(self) -> None:
        self.app.push_screen("refresh")
