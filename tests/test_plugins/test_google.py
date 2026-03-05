"""Unit tests for the Google plugin (mocked gcloud + httpx)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_context.plugins.google import GooglePlugin, _gcloud_token

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
FIXTURE = json.loads((FIXTURE_DIR / "gws_drive_output.json").read_text())


def _make_plugin(config: dict | None = None) -> GooglePlugin:
    return GooglePlugin(config or {})


@pytest.mark.asyncio
async def test_gcloud_token_missing_gcloud() -> None:
    with patch("shutil.which", return_value=None):
        token = await _gcloud_token()
    assert token is None


@pytest.mark.asyncio
async def test_health_no_gcloud() -> None:
    with (
        patch("shutil.which", return_value=None),
        patch("agent_context.plugins.google._get_token", side_effect=Exception("no gcloud")),
    ):
        plugin = _make_plugin()
        status = await plugin.health()

    assert not status.cli_available
    assert not status.authenticated
    assert status.error is not None


@pytest.mark.asyncio
async def test_health_authenticated() -> None:
    with (
        patch("shutil.which", return_value="/usr/bin/gcloud"),
        patch(
            "agent_context.plugins.google._get_token",
            new_callable=AsyncMock,
            return_value="fake-token",
        ),
    ):
        plugin = _make_plugin()
        status = await plugin.health()

    assert status.cli_available
    assert status.authenticated
    assert status.healthy


@pytest.mark.asyncio
async def test_fetch_produces_documents(tmp_path) -> None:
    """Drive file listing + export produces Document objects."""
    import httpx

    # Build a mock httpx response for the files list
    files_response = MagicMock(spec=httpx.Response)
    files_response.status_code = 200
    files_response.json.return_value = FIXTURE
    files_response.raise_for_status = MagicMock()

    # Export response for Docs
    export_response = MagicMock(spec=httpx.Response)
    export_response.status_code = 200
    export_response.text = "Dark mode, performance improvements, and the scheduler refactor."

    # Plain-text download response
    dl_response = MagicMock(spec=httpx.Response)
    dl_response.status_code = 200
    dl_response.text = "Sprint notes content here."

    async def mock_get(url, **kwargs):
        if (
            "drive/v3/files" in url
            and "export" not in url
            and "alt=media" not in str(kwargs.get("params", {}))
        ):
            return files_response
        if "export" in url:
            return export_response
        if "alt=media" in str(kwargs.get("params", {})):
            return dl_response
        return files_response

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=mock_get)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "agent_context.plugins.google._get_token",
            new_callable=AsyncMock,
            return_value="fake-token",
        ),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        plugin = _make_plugin()
        docs = []
        async for doc in plugin.fetch():
            docs.append(doc)

    assert len(docs) == 2
    assert all(d.source == "google" for d in docs)
    doc_types = {d.doc_type for d in docs}
    assert "doc" in doc_types
