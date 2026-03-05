"""Unit tests for the GitHub plugin (mocked gh CLI)."""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_context.plugins.github import GitHubPlugin

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
ISSUES = json.loads((FIXTURE_DIR / "gh_output.json").read_text())


def _make_plugin(config: dict | None = None) -> GitHubPlugin:
    return GitHubPlugin(config or {})


@pytest.mark.asyncio
async def test_fetch_issues_basic() -> None:
    """Issues returned by gh CLI are converted to Documents correctly."""
    plugin = _make_plugin({"repos": ["myorg/myrepo"], "include_prs": False, "include_wiki": False})

    with patch("agent_context.plugins.github._gh", new_callable=AsyncMock) as mock_gh:
        mock_gh.return_value = json.dumps(ISSUES)
        docs = []
        async for doc in plugin.fetch():
            docs.append(doc)

    assert len(docs) == 2
    assert all(d.source == "github" for d in docs)
    assert all(d.doc_type == "issue" for d in docs)
    assert any("race condition" in d.content for d in docs)


@pytest.mark.asyncio
async def test_fetch_issues_since_filter() -> None:
    """Documents updated before `since` are excluded."""
    from datetime import datetime

    plugin = _make_plugin({"repos": ["myorg/myrepo"], "include_prs": False, "include_wiki": False})
    # Both fixtures have updatedAt in Jan or Mar 2025; cut at Feb 1
    cutoff = datetime(2025, 2, 1, tzinfo=UTC)

    with patch("agent_context.plugins.github._gh", new_callable=AsyncMock) as mock_gh:
        mock_gh.return_value = json.dumps(ISSUES)
        docs = []
        async for doc in plugin.fetch(since=cutoff):
            docs.append(doc)

    # Only the Mar 2025 issue should pass the filter
    assert len(docs) == 1
    assert "42" in docs[0].source_id


@pytest.mark.asyncio
async def test_health_gh_not_installed() -> None:
    with patch("shutil.which", return_value=None):
        plugin = _make_plugin()
        status = await plugin.health()

    assert not status.cli_available
    assert not status.authenticated
    assert not status.healthy


@pytest.mark.asyncio
async def test_health_authenticated() -> None:
    with (
        patch("shutil.which", return_value="/usr/bin/gh"),
        patch("agent_context.plugins.github._gh", new_callable=AsyncMock) as mock_gh,
    ):
        mock_gh.return_value = ""
        plugin = _make_plugin()
        status = await plugin.health()

    assert status.cli_available
    assert status.authenticated
    assert status.healthy


@pytest.mark.asyncio
async def test_metadata_populated() -> None:
    plugin = _make_plugin({"repos": ["myorg/myrepo"], "include_prs": False, "include_wiki": False})

    with patch("agent_context.plugins.github._gh", new_callable=AsyncMock) as mock_gh:
        mock_gh.return_value = json.dumps([ISSUES[0]])
        docs = []
        async for doc in plugin.fetch():
            docs.append(doc)

    doc = docs[0]
    assert doc.metadata["repo"] == "myorg/myrepo"
    assert doc.metadata["number"] == 42
    assert "bug" in doc.metadata["labels"]
