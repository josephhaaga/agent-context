"""Unit tests for the Slack plugin (mocked slackcli)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_context.plugins.slack import SlackPlugin, _strip_slack_markup

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
FIXTURE = json.loads((FIXTURE_DIR / "slackcli_output.json").read_text())
CHANNELS = FIXTURE["channels"]
MESSAGES = FIXTURE["messages"]


def _make_plugin(config: dict | None = None) -> SlackPlugin:
    return SlackPlugin(config or {"workspace": "acme"})


class TestStripMarkup:
    def test_user_mention(self):
        assert _strip_slack_markup("<@U123ABC>") == "@user"

    def test_channel_link(self):
        assert _strip_slack_markup("<#C123|engineering>") == "#engineering"

    def test_url_with_label(self):
        assert _strip_slack_markup("<https://example.com|click here>") == "click here"

    def test_bare_url(self):
        assert _strip_slack_markup("<https://example.com>") == "https://example.com"

    def test_no_markup(self):
        assert _strip_slack_markup("hello world") == "hello world"


@pytest.mark.asyncio
async def test_fetch_messages_basic() -> None:
    plugin = _make_plugin(
        {"channels": ["engineering"], "workspace": "acme", "include_threads": False}
    )

    async def mock_slackcli(*args):
        if "channel" in args and "list" in args:
            return json.dumps(CHANNELS)
        if "message" in args and "list" in args:
            return json.dumps(MESSAGES)
        return "[]"

    with patch("agent_context.plugins.slack._slackcli", side_effect=mock_slackcli):
        docs = []
        async for doc in plugin.fetch():
            docs.append(doc)

    assert len(docs) == len(MESSAGES)
    assert all(d.source == "slack" for d in docs)


@pytest.mark.asyncio
async def test_fetch_url_construction() -> None:
    plugin = _make_plugin(
        {"channels": ["engineering"], "workspace": "acme", "include_threads": False}
    )

    async def mock_slackcli(*args):
        if "channel" in args and "list" in args:
            return json.dumps(CHANNELS)
        if "message" in args and "list" in args:
            return json.dumps(MESSAGES)
        return "[]"

    with patch("agent_context.plugins.slack._slackcli", side_effect=mock_slackcli):
        docs = []
        async for doc in plugin.fetch():
            docs.append(doc)

    for doc in docs:
        if doc.url:
            assert "acme.slack.com" in doc.url


@pytest.mark.asyncio
async def test_health_not_installed() -> None:
    with patch("shutil.which", return_value=None):
        plugin = _make_plugin()
        status = await plugin.health()

    assert not status.cli_available
    assert not status.authenticated


@pytest.mark.asyncio
async def test_health_authenticated() -> None:
    with (
        patch("shutil.which", return_value="/usr/local/bin/slackcli"),
        patch("agent_context.plugins.slack._slackcli", new_callable=AsyncMock) as mock_sc,
    ):
        mock_sc.return_value = ""
        plugin = _make_plugin()
        status = await plugin.health()

    assert status.cli_available
    assert status.authenticated
