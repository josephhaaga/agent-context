"""Output formatters for CLI results."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from agent_context.models import SearchResult, SourceStatus

console = Console()


def _score_bar(score: float, width: int = 10) -> str:
    filled = round(score * width)
    return "█" * filled + "░" * (width - filled)


def print_results_human(results: list[SearchResult], query: str) -> None:
    """Print search results in a readable human format."""
    if not results:
        console.print(f"[yellow]No results for:[/yellow] {query}")
        return

    console.print(
        f"\n[bold]Results for:[/bold] [cyan]{query}[/cyan]  ([dim]{len(results)} found[/dim])\n"
    )

    for i, r in enumerate(results, 1):
        doc = r.document
        score_bar = _score_bar(r.score)
        console.print(
            f"[bold]{i}.[/bold] [green]{doc.title}[/green]  [dim]{score_bar} {r.score:.2f}[/dim]"
        )
        console.print(
            f"   [dim]source:[/dim] {doc.source}  "
            f"[dim]type:[/dim] {doc.doc_type}  "
            + (f"[dim]updated:[/dim] {doc.updated_at.date()}" if doc.updated_at else "")
        )
        if doc.url:
            console.print(f"   [blue underline]{doc.url}[/blue underline]")
        if r.excerpt:
            console.print(f"   [italic dim]{r.excerpt[:160]}[/italic dim]")
        console.print()


def print_results_json(results: list[SearchResult]) -> None:
    """Print search results as a JSON array (machine/agent-friendly)."""
    data: list[dict[str, Any]] = [r.to_dict() for r in results]
    print(json.dumps(data, indent=2, default=str))


def print_status_human(statuses: list[SourceStatus]) -> None:
    """Print source status as a rich table."""
    table = Table(title="Source Status", show_header=True, header_style="bold cyan")
    table.add_column("Source", style="bold")
    table.add_column("Enabled")
    table.add_column("CLI")
    table.add_column("Authed")
    table.add_column("Docs")
    table.add_column("Last Indexed")
    table.add_column("Error", style="red")

    def _bool(v: bool) -> Text:  # noqa: A002
        return Text("✓", style="green") if v else Text("✗", style="red")

    for s in statuses:
        table.add_row(
            s.name,
            _bool(s.enabled),
            _bool(s.cli_available),
            _bool(s.authenticated),
            str(s.document_count),
            str(s.last_indexed.date()) if s.last_indexed else "—",
            s.error or "",
        )

    console.print(table)


def print_status_json(statuses: list[SourceStatus]) -> None:
    data = [s.to_dict() for s in statuses]
    print(json.dumps(data, indent=2, default=str))
