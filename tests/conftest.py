"""Shared pytest fixtures for agent-context tests."""

from __future__ import annotations

import asyncio
from datetime import UTC
from pathlib import Path

import pytest
import pytest_asyncio

from agent_context.config.models import AppConfig, PluginConfig, SearchConfig
from agent_context.models import Document
from agent_context.storage.database import Database


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:
    """Provide a fresh, connected in-memory-ish Database for each test."""
    db_path = tmp_path / "test.db"
    async with Database(db_path) as database:
        yield database


@pytest.fixture
def sample_doc() -> Document:
    from datetime import datetime

    return Document(
        source="github",
        source_id="myorg/myrepo#issue#42",
        doc_type="issue",
        title="[myorg/myrepo] #42: Fix the flaky tests",
        content="The tests on CI are randomly failing due to a race condition in the scheduler.",
        url="https://github.com/myorg/myrepo/issues/42",
        author="alice",
        created_at=datetime(2025, 1, 10, tzinfo=UTC),
        updated_at=datetime(2025, 3, 1, tzinfo=UTC),
        metadata={"repo": "myorg/myrepo", "number": 42, "state": "open"},
    )


@pytest.fixture
def sample_docs() -> list[Document]:
    from datetime import datetime

    return [
        Document(
            source="github",
            source_id="myorg/myrepo#issue#1",
            doc_type="issue",
            title="[myorg/myrepo] #1: Add dark mode support",
            content="Users are requesting dark mode. We should implement it using CSS variables.",
            url="https://github.com/myorg/myrepo/issues/1",
            author="bob",
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
            updated_at=datetime(2025, 1, 15, tzinfo=UTC),
        ),
        Document(
            source="github",
            source_id="myorg/myrepo#pr#99",
            doc_type="pr",
            title="[myorg/myrepo] PR #99: Implement dark mode",
            content="This PR adds dark mode by introducing CSS variables for all colour tokens.",
            url="https://github.com/myorg/myrepo/pull/99",
            author="alice",
            created_at=datetime(2025, 2, 1, tzinfo=UTC),
            updated_at=datetime(2025, 2, 20, tzinfo=UTC),
        ),
        Document(
            source="slack",
            source_id="C123:1704100000.000100",
            doc_type="message",
            title="#engineering: Has anyone looked at the scheduler race condition?",
            content="Has anyone looked at the scheduler race condition? It keeps causing flaky tests.",
            url="https://acme.slack.com/archives/C123/p1704100000000100",
            author="charlie",
            created_at=datetime(2025, 1, 5, tzinfo=UTC),
            updated_at=datetime(2025, 1, 5, tzinfo=UTC),
        ),
        Document(
            source="google",
            source_id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
            doc_type="doc",
            title="Q1 Engineering Roadmap",
            content="Dark mode, performance improvements, and the scheduler refactor are top priorities.",
            url="https://docs.google.com/document/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
            author="dave@example.com",
            created_at=datetime(2025, 1, 2, tzinfo=UTC),
            updated_at=datetime(2025, 2, 28, tzinfo=UTC),
        ),
    ]


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        db_path=tmp_path / "test.db",
        search=SearchConfig(semantic=False),  # disable semantic in unit tests
        plugins={
            "github": PluginConfig(enabled=True),
            "google": PluginConfig(enabled=True),
            "slack": PluginConfig(enabled=True),
        },
    )
