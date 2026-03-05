# agent-context

Search across scattered documentation — GitHub, Google Workspace, Slack, and more — from a single CLI or interactive TUI.

Built for humans and AI agents alike. No IT approvals, no registering new OAuth apps: leverages CLIs and browser tokens you already have.

## Quick Start

```bash
pip install agent-context

agent-context init        # interactive setup wizard
agent-context search "api authentication design"
agent-context            # launch TUI
```

## Data Sources

| Source | Auth mechanism |
|---|---|
| GitHub | `gh` CLI (already authenticated) |
| Google Workspace (Drive, Docs) | `gcloud auth login --enable-gdrive-access` |
| Slack | Browser token via `slackcli auth parse-curl --login` |

## Commands

```bash
agent-context init                          # interactive setup wizard
agent-context search "query"                # search all sources
agent-context search "query" --source github --format json
agent-context refresh                       # re-index all sources
agent-context status                        # index health and last-updated times
agent-context sources list                  # list configured sources
agent-context sources reauth slack          # re-authenticate a source
agent-context config show                   # print current config
agent-context config edit                   # open config in $EDITOR
agent-context tui                           # launch interactive TUI
```

## Configuration

Config lives at `~/.config/agent-context/config.yaml`. Run `agent-context init` to generate it interactively, or edit directly.

## Privacy

Sensitive content (Slack DMs, Gmail) is excluded by default. Enable per-source opt-in in your config. The local index at `~/.local/share/agent-context/index.db` contains indexed text — it is only as private as your machine.
