"""Plugin base class and discovery for agent-context."""

from __future__ import annotations

import importlib.metadata
from abc import ABC, abstractmethod
from datetime import datetime
from typing import AsyncIterator

from agent_context.models import Document, SourceStatus


class PluginError(Exception):
    """Raised when a plugin encounters a non-retryable error."""


class AuthError(PluginError):
    """Raised when a plugin's credentials are missing or expired."""


class CLINotFoundError(PluginError):
    """Raised when a required CLI tool is not installed."""


class BasePlugin(ABC):
    """Abstract base class for all agent-context source plugins.

    Subclasses must implement:
    - ``name``: unique lowercase string identifier (e.g. 'github')
    - ``fetch()``: async generator yielding Document objects
    - ``health()``: returns a SourceStatus reflecting current state
    - ``reauth()``: interactive re-authentication flow
    """

    #: Unique identifier for this plugin, e.g. 'github', 'google', 'slack'
    name: str

    def __init__(self, config: dict) -> None:
        """
        Args:
            config: Plugin-specific config dict from the global config file.
                    Plugins should be tolerant of missing keys and use defaults.
        """
        self.config = config

    @abstractmethod
    async def fetch(
        self,
        since: datetime | None = None,
    ) -> AsyncIterator[Document]:
        """Yield documents from the source.

        Args:
            since: If provided, only return documents updated after this time.
                   Plugins may ignore this if the source does not support it.

        Yields:
            Document objects ready for indexing.

        Raises:
            AuthError: Credentials are missing or expired.
            CLINotFoundError: Required CLI is not installed.
            PluginError: Any other non-retryable error.
        """
        # Make this a proper async generator
        return
        yield  # type: ignore[misc]

    @abstractmethod
    async def health(self) -> SourceStatus:
        """Return the current health and index status of this source.

        Should not raise; capture errors in SourceStatus.error instead.
        """
        ...

    async def reauth(self) -> None:
        """Interactive re-authentication.

        Override in plugins that support token refresh / re-login.
        Default implementation raises NotImplementedError.
        """
        raise NotImplementedError(
            f"Plugin '{self.name}' does not support interactive reauth. "
            "Please re-authenticate manually."
        )


# ---------------------------------------------------------------------------
# Plugin registry + entry-point discovery
# ---------------------------------------------------------------------------

_BUILTIN_PLUGINS: dict[str, type[BasePlugin]] = {}


def register(cls: type[BasePlugin]) -> type[BasePlugin]:
    """Class decorator to register a built-in plugin."""
    _BUILTIN_PLUGINS[cls.name] = cls
    return cls


def discover_plugins() -> dict[str, type[BasePlugin]]:
    """Return all available plugin classes, built-in + installed via entry points.

    Third-party packages can register plugins by declaring an entry point in
    their ``pyproject.toml``::

        [project.entry-points."agent_context.plugins"]
        myplugin = "mypkg.plugin:MyPlugin"

    Returns:
        Mapping of plugin name → plugin class.
    """
    plugins: dict[str, type[BasePlugin]] = dict(_BUILTIN_PLUGINS)

    # Load third-party plugins via entry points
    for ep in importlib.metadata.entry_points(group="agent_context.plugins"):
        try:
            cls = ep.load()
            if not (isinstance(cls, type) and issubclass(cls, BasePlugin)):
                continue
            plugins[cls.name] = cls
        except Exception:  # noqa: BLE001
            pass

    return plugins
