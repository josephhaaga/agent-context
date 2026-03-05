"""Config file loading and saving for agent-context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_context.config.models import AppConfig

# Default config file location (XDG-ish)
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "agent-context" / "config.yaml"


def load_config(path: Path | None = None) -> AppConfig:
    """Load config from YAML file.

    If the file does not exist, a default AppConfig is returned (no error).

    Args:
        path: Path to config YAML. Defaults to ``~/.config/agent-context/config.yaml``.

    Returns:
        Parsed AppConfig.
    """
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return AppConfig()

    with config_path.open() as fh:
        raw: Any = yaml.safe_load(fh)

    if not raw or not isinstance(raw, dict):
        return AppConfig()

    return AppConfig.from_dict(raw)


def save_config(config: AppConfig, path: Path | None = None) -> None:
    """Write config to YAML file.

    Args:
        config: AppConfig to persist.
        path: Destination path. Defaults to ``~/.config/agent-context/config.yaml``.
    """
    config_path = path or DEFAULT_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with config_path.open("w") as fh:
        yaml.dump(config.to_dict(), fh, default_flow_style=False, sort_keys=True)


def config_path(path: Path | None = None) -> Path:
    """Return the resolved config file path."""
    return path or DEFAULT_CONFIG_PATH
