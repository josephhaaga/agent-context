"""TUI detail screen — shows a single document."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Markdown, Static

from agent_context.models import SearchResult


class DetailScreen(Screen):
    """Full-content view for a single search result."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    CSS = """
    #meta {
        margin: 1 2;
        color: $text-muted;
        text-style: dim;
    }
    #content {
        margin: 0 2;
        height: 1fr;
        overflow-y: auto;
    }
    """

    def __init__(self, result: SearchResult, **kwargs) -> None:
        super().__init__(**kwargs)
        self._result = result

    def compose(self) -> ComposeResult:
        doc = self._result.document
        yield Header(show_clock=True)

        meta_parts = [
            f"source: {doc.source}",
            f"type: {doc.doc_type}",
        ]
        if doc.author:
            meta_parts.append(f"author: {doc.author}")
        if doc.updated_at:
            meta_parts.append(f"updated: {doc.updated_at.date()}")
        if doc.url:
            meta_parts.append(f"url: {doc.url}")
        meta_parts.append(f"score: {self._result.score:.3f}")

        yield Static("  ·  ".join(meta_parts), id="meta")
        yield Markdown(doc.content or "*No content available.*", id="content")
        yield Footer()
