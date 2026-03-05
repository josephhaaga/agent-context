"""Interactive init wizard for agent-context."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt

from agent_context.config.loader import DEFAULT_CONFIG_PATH, save_config
from agent_context.config.models import AppConfig, PluginConfig, SearchConfig

console = Console()


def run_wizard(config_path: Path | None = None) -> AppConfig:
    """Run interactive setup wizard and write config file.

    Returns the resulting AppConfig.
    """
    dest = config_path or DEFAULT_CONFIG_PATH
    console.print("\n[bold cyan]agent-context setup wizard[/bold cyan]\n")
    console.print(f"Config will be written to: [green]{dest}[/green]\n")

    # --- Database path ---
    default_db = str(Path.home() / ".local" / "share" / "agent-context" / "index.db")
    db_path_str = Prompt.ask("Database path", default=default_db)
    db_path = Path(db_path_str)

    # --- GitHub ---
    enable_github = Confirm.ask("Enable GitHub plugin?", default=True)
    github_cfg: dict = {"enabled": enable_github}
    if enable_github:
        repos_input = Prompt.ask(
            "Specific repos to index (comma-separated owner/repo, or leave blank for all)",
            default="",
        )
        if repos_input.strip():
            github_cfg["repos"] = [r.strip() for r in repos_input.split(",") if r.strip()]
        github_cfg["max_repos"] = IntPrompt.ask("Max repos to auto-discover", default=50)
        github_cfg["include_issues"] = Confirm.ask("Index issues?", default=True)
        github_cfg["include_prs"] = Confirm.ask("Index pull requests?", default=True)
        github_cfg["include_wiki"] = Confirm.ask("Index wiki pages?", default=False)

    # --- Google ---
    enable_google = Confirm.ask("Enable Google Workspace (Drive) plugin?", default=True)
    google_cfg: dict = {"enabled": enable_google}
    if enable_google:
        console.print(
            "[dim]Tip: run [bold]gcloud auth login --enable-gdrive-access[/bold] "
            "to grant Drive access before indexing.[/dim]"
        )
        google_cfg["include_shared"] = Confirm.ask("Include files shared with you?", default=True)
        google_cfg["file_limit"] = IntPrompt.ask("Max files to index", default=500)

    # --- Slack ---
    enable_slack = Confirm.ask("Enable Slack plugin?", default=False)
    slack_cfg: dict = {"enabled": enable_slack}
    if enable_slack:
        workspace = Prompt.ask(
            "Slack workspace subdomain (e.g. acme for acme.slack.com)", default=""
        )
        if workspace:
            slack_cfg["workspace"] = workspace
        channels_input = Prompt.ask(
            "Channels to index (comma-separated, without #, or blank for auto)",
            default="",
        )
        if channels_input.strip():
            slack_cfg["channels"] = [
                c.strip().lstrip("#") for c in channels_input.split(",") if c.strip()
            ]
        slack_cfg["max_channels"] = IntPrompt.ask("Max channels to auto-discover", default=20)
        slack_cfg["include_threads"] = Confirm.ask("Include thread replies?", default=True)
        console.print(
            "[dim]Tip: authenticate with [bold]slackcli auth parse-curl --login[/bold][/dim]"
        )

    # --- Search ---
    enable_semantic = Confirm.ask("Enable semantic (embedding) search?", default=True)
    search_cfg = SearchConfig(
        semantic=enable_semantic,
        keyword_weight=0.6 if enable_semantic else 1.0,
        semantic_weight=0.4 if enable_semantic else 0.0,
    )

    # --- Build and save ---
    config = AppConfig(
        db_path=db_path,
        search=search_cfg,
        plugins={
            "github": PluginConfig.from_dict(github_cfg),
            "google": PluginConfig.from_dict(google_cfg),
            "slack": PluginConfig.from_dict(slack_cfg),
        },
    )

    save_config(config, dest)
    console.print(f"\n[bold green]Config saved to {dest}[/bold green]")
    console.print("Run [bold]agent-context status[/bold] to verify source health.\n")
    return config
