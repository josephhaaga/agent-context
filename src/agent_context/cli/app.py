"""Main CLI application for agent-context."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

import typer
import yaml
from rich.console import Console

from agent_context.cli.formatters import (
    print_results_human,
    print_results_json,
    print_status_human,
    print_status_json,
)
from agent_context.config.loader import DEFAULT_CONFIG_PATH, config_path, load_config, save_config
from agent_context.config.wizard import run_wizard
from agent_context.models import SourceStatus
from agent_context.plugins.base import AuthError, CLINotFoundError, PluginError, discover_plugins
from agent_context.search.engine import search as hybrid_search
from agent_context.search.semantic import build_embeddings
from agent_context.storage.database import Database

app = typer.Typer(
    name="agent-context",
    help="Index and search enterprise documentation from GitHub, Google Workspace, and Slack.",
    no_args_is_help=False,
    invoke_without_command=True,
)
sources_app = typer.Typer(help="Manage data sources.")
config_app = typer.Typer(help="Manage configuration.")
app.add_typer(sources_app, name="sources")
app.add_typer(config_app, name="config")

console = Console()

_FORMAT_CHOICES = ["human", "json"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_cfg(config: Optional[Path]):
    return load_config(config)


def _run(coro):
    return asyncio.run(coro)


def _now_utc() -> datetime:
    from datetime import timezone

    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Root command — defaults to TUI
# ---------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    config: Annotated[
        Optional[Path], typer.Option("--config", "-c", help="Config file path")
    ] = None,
) -> None:
    """Launch the interactive TUI when called with no subcommand."""
    if ctx.invoked_subcommand is None:
        _launch_tui(config)


def _launch_tui(config: Optional[Path]) -> None:
    try:
        from agent_context.tui.app import AgentContextApp  # noqa: PLC0415

        cfg = _load_cfg(config)
        AgentContextApp(cfg).run()
    except ImportError as exc:
        console.print(f"[red]TUI unavailable:[/red] {exc}")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@app.command()
def init(
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Run interactive setup wizard."""
    run_wizard(config)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query")],
    source: Annotated[
        Optional[str], typer.Option("--source", "-s", help="Filter by source name")
    ] = None,
    format: Annotated[
        str, typer.Option("--format", "-f", help="Output format: human or json")
    ] = "human",
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max results")] = 0,
    after: Annotated[
        Optional[str], typer.Option("--after", help="ISO date filter e.g. 2025-01-01")
    ] = None,
    semantic: Annotated[
        bool, typer.Option("--semantic/--no-semantic", help="Enable semantic search")
    ] = True,
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Search indexed documents."""
    cfg = _load_cfg(config)
    effective_limit = limit or cfg.search.default_limit

    sources_filter = [source] if source else None
    after_dt: Optional[datetime] = None
    if after:
        try:
            from datetime import timezone  # noqa: PLC0415

            after_dt = datetime.fromisoformat(after).replace(tzinfo=timezone.utc)
        except ValueError:
            console.print(f"[red]Invalid --after date:[/red] {after}")
            raise typer.Exit(1)

    use_semantic = semantic and cfg.search.semantic

    async def _search():
        async with Database(cfg.db_path) as db:
            return await hybrid_search(
                db,
                query,
                sources=sources_filter,
                limit=effective_limit,
                after=after_dt,
                semantic=use_semantic,
                keyword_weight=cfg.search.keyword_weight,
                semantic_weight=cfg.search.semantic_weight,
                model_name=cfg.search.model,
            )

    results = _run(_search())

    if format == "json":
        print_results_json(results)
    else:
        print_results_human(results, query)


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------


@app.command()
def refresh(
    source: Annotated[
        Optional[str], typer.Option("--source", "-s", help="Refresh only this source")
    ] = None,
    build_index: Annotated[
        bool,
        typer.Option("--embeddings/--no-embeddings", help="Generate embeddings after indexing"),
    ] = True,
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Fetch and index documents from sources."""
    cfg = _load_cfg(config)
    plugins = discover_plugins()

    targets = {source: plugins[source]} if source else plugins
    for name in list(targets.keys()):
        plugin_cfg = cfg.plugin(name).as_plugin_dict()
        if not plugin_cfg.get("enabled", True):
            console.print(f"[dim]Skipping {name} (disabled)[/dim]")
            targets.pop(name)

    if not targets:
        console.print("[yellow]No enabled sources to refresh.[/yellow]")
        raise typer.Exit(0)

    async def _refresh():
        async with Database(cfg.db_path) as db:
            for name, plugin_cls in targets.items():
                plugin_cfg_dict = cfg.plugin(name).as_plugin_dict()
                plugin = plugin_cls(plugin_cfg_dict)
                console.print(f"[bold]Refreshing[/bold] [cyan]{name}[/cyan]…")
                count = 0
                error: Optional[str] = None
                try:
                    async for doc in plugin.fetch():
                        await db.upsert_document(doc)
                        count += 1
                        if count % 50 == 0:
                            console.print(f"  {count} documents indexed…", end="\r")
                except (AuthError, CLINotFoundError, PluginError) as exc:
                    error = str(exc)
                    console.print(f"[red]  Error:[/red] {exc}")

                await db.update_source_meta(name, last_error=error)
                console.print(f"  [green]{count}[/green] documents indexed for [cyan]{name}[/cyan]")

            if build_index and cfg.search.semantic:
                console.print("\n[bold]Building embeddings…[/bold]")
                n = await build_embeddings(db, model_name=cfg.search.model)
                console.print(f"  [green]{n}[/green] new embeddings generated")

    _run(_refresh())


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status(
    format: Annotated[str, typer.Option("--format", "-f")] = "human",
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Show health and index status for all sources."""
    cfg = _load_cfg(config)
    plugins = discover_plugins()

    async def _status() -> list[SourceStatus]:
        statuses: list[SourceStatus] = []
        async with Database(cfg.db_path) as db:
            for name, plugin_cls in plugins.items():
                plugin_cfg_dict = cfg.plugin(name).as_plugin_dict()
                plugin = plugin_cls(plugin_cfg_dict)
                s = await plugin.health()
                # Enrich with DB counts
                s.document_count = await db.document_count(name)
                meta = await db.get_source_meta(name)
                last_indexed_str = meta.get("last_indexed")
                if last_indexed_str:
                    s.last_indexed = datetime.fromisoformat(str(last_indexed_str))
                statuses.append(s)
        return statuses

    statuses = _run(_status())

    if format == "json":
        print_status_json(statuses)
    else:
        print_status_human(statuses)


# ---------------------------------------------------------------------------
# sources sub-commands
# ---------------------------------------------------------------------------


@sources_app.command("list")
def sources_list(
    format: Annotated[str, typer.Option("--format", "-f")] = "human",
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """List available source plugins."""
    plugins = discover_plugins()
    if format == "json":
        import json  # noqa: PLC0415

        print(json.dumps(list(plugins.keys())))
    else:
        for name in plugins:
            console.print(f"  • {name}")


@sources_app.command("test")
def sources_test(
    source_name: Annotated[str, typer.Argument(help="Source name to test")],
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Test connectivity for a specific source."""
    plugins = discover_plugins()
    if source_name not in plugins:
        console.print(f"[red]Unknown source:[/red] {source_name}")
        raise typer.Exit(1)

    cfg = _load_cfg(config)
    plugin_cfg_dict = cfg.plugin(source_name).as_plugin_dict()
    plugin = plugins[source_name](plugin_cfg_dict)

    async def _test():
        return await plugin.health()

    s = _run(_test())
    if s.healthy:
        console.print(f"[green]✓[/green] {source_name} is healthy")
    else:
        console.print(f"[red]✗[/red] {source_name}: {s.error or 'not healthy'}")
        raise typer.Exit(1)


@sources_app.command("reauth")
def sources_reauth(
    source_name: Annotated[str, typer.Argument(help="Source name to re-authenticate")],
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Re-authenticate a source (interactive)."""
    plugins = discover_plugins()
    if source_name not in plugins:
        console.print(f"[red]Unknown source:[/red] {source_name}")
        raise typer.Exit(1)

    cfg = _load_cfg(config)
    plugin_cfg_dict = cfg.plugin(source_name).as_plugin_dict()
    plugin = plugins[source_name](plugin_cfg_dict)

    async def _reauth():
        await plugin.reauth()

    _run(_reauth())


# ---------------------------------------------------------------------------
# config sub-commands
# ---------------------------------------------------------------------------


@config_app.command("show")
def config_show(
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Print the current config file."""
    path = config_path(config)
    if not path.exists():
        console.print(f"[yellow]No config file found at {path}[/yellow]")
        console.print("Run [bold]agent-context init[/bold] to create one.")
        return
    console.print(f"[dim]# {path}[/dim]\n")
    console.print(path.read_text())


@config_app.command("edit")
def config_edit(
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Open the config file in $EDITOR."""
    import os  # noqa: PLC0415

    path = config_path(config)
    if not path.exists():
        console.print(f"[yellow]Config not found. Running init first…[/yellow]")
        run_wizard(path)
        return
    editor = os.environ.get("EDITOR", "vi")
    subprocess.run([editor, str(path)], check=False)


# ---------------------------------------------------------------------------
# tui
# ---------------------------------------------------------------------------


@app.command()
def tui(
    config: Annotated[Optional[Path], typer.Option("--config", "-c")] = None,
) -> None:
    """Launch the interactive TUI."""
    _launch_tui(config)
