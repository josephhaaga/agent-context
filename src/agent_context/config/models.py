"""Config data models for agent-context."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PluginConfig:
    """Per-plugin configuration block."""

    enabled: bool = True
    # Arbitrary plugin-specific keys are stored in `extra`
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"enabled": self.enabled}
        d.update(self.extra)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginConfig:
        enabled = data.pop("enabled", True)
        return cls(enabled=enabled, extra=dict(data))

    def as_plugin_dict(self) -> dict[str, Any]:
        """Return a flat dict with 'enabled' + all extra keys merged — suitable
        for passing directly to plugin constructors."""
        d = {"enabled": self.enabled}
        d.update(self.extra)
        return d


@dataclass
class SearchConfig:
    """Search engine settings."""

    semantic: bool = True
    keyword_weight: float = 0.6
    semantic_weight: float = 0.4
    model: str = "all-MiniLM-L6-v2"
    default_limit: int = 20

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SearchConfig:
        return cls(
            semantic=data.get("semantic", True),
            keyword_weight=float(data.get("keyword_weight", 0.6)),
            semantic_weight=float(data.get("semantic_weight", 0.4)),
            model=data.get("model", "all-MiniLM-L6-v2"),
            default_limit=int(data.get("default_limit", 20)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic": self.semantic,
            "keyword_weight": self.keyword_weight,
            "semantic_weight": self.semantic_weight,
            "model": self.model,
            "default_limit": self.default_limit,
        }


@dataclass
class AppConfig:
    """Root application configuration."""

    db_path: Path = field(
        default_factory=lambda: Path.home() / ".local" / "share" / "agent-context" / "index.db"
    )
    search: SearchConfig = field(default_factory=SearchConfig)
    plugins: dict[str, PluginConfig] = field(default_factory=dict)

    def plugin(self, name: str) -> PluginConfig:
        """Return plugin config, creating a default one if not present."""
        if name not in self.plugins:
            self.plugins[name] = PluginConfig()
        return self.plugins[name]

    def to_dict(self) -> dict[str, Any]:
        return {
            "db_path": str(self.db_path),
            "search": self.search.to_dict(),
            "plugins": {k: v.to_dict() for k, v in self.plugins.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        db_path = Path(
            data.get(
                "db_path", str(Path.home() / ".local" / "share" / "agent-context" / "index.db")
            )
        )
        search = SearchConfig.from_dict(data.get("search", {}))
        raw_plugins = data.get("plugins", {})
        plugins = {name: PluginConfig.from_dict(dict(cfg)) for name, cfg in raw_plugins.items()}
        return cls(db_path=db_path, search=search, plugins=plugins)
