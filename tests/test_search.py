"""Tests for the search layer (FTS, hybrid)."""

from __future__ import annotations

import pytest

from agent_context.models import Document, SearchResult
from agent_context.search.engine import search as hybrid_search
from agent_context.search.fts import keyword_search
from agent_context.storage.database import Database


@pytest.mark.asyncio
async def test_keyword_search_basic(db: Database, sample_docs: list[Document]) -> None:
    await db.upsert_documents(sample_docs)
    results = await keyword_search(db, "dark mode")
    assert len(results) > 0
    titles = [r.document.title for r in results]
    assert any("dark mode" in t.lower() or "dark" in t.lower() for t in titles)


@pytest.mark.asyncio
async def test_keyword_search_no_results(db: Database, sample_docs: list[Document]) -> None:
    await db.upsert_documents(sample_docs)
    results = await keyword_search(db, "xyzzy_nonexistent_token_12345")
    assert results == []


@pytest.mark.asyncio
async def test_keyword_search_source_filter(db: Database, sample_docs: list[Document]) -> None:
    await db.upsert_documents(sample_docs)
    results = await keyword_search(db, "dark mode", sources=["github"])
    for r in results:
        assert r.document.source == "github"


@pytest.mark.asyncio
async def test_keyword_search_scores_normalized(db: Database, sample_docs: list[Document]) -> None:
    await db.upsert_documents(sample_docs)
    results = await keyword_search(db, "dark mode")
    for r in results:
        assert 0.0 <= r.keyword_score <= 1.0


@pytest.mark.asyncio
async def test_keyword_search_sorted_descending(db: Database, sample_docs: list[Document]) -> None:
    await db.upsert_documents(sample_docs)
    results = await keyword_search(db, "dark mode")
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_hybrid_search_no_semantic(db: Database, sample_docs: list[Document]) -> None:
    """Hybrid search with semantic=False should behave like keyword-only."""
    await db.upsert_documents(sample_docs)
    results = await hybrid_search(db, "scheduler race condition", semantic=False)
    assert len(results) > 0
    for r in results:
        assert r.semantic_score == 0.0


@pytest.mark.asyncio
async def test_hybrid_search_source_filter(db: Database, sample_docs: list[Document]) -> None:
    await db.upsert_documents(sample_docs)
    results = await hybrid_search(db, "dark mode", sources=["slack"], semantic=False)
    for r in results:
        assert r.document.source == "slack"


@pytest.mark.asyncio
async def test_hybrid_search_limit(db: Database, sample_docs: list[Document]) -> None:
    await db.upsert_documents(sample_docs)
    results = await hybrid_search(db, "dark mode", limit=1, semantic=False)
    assert len(results) <= 1


@pytest.mark.asyncio
async def test_hybrid_search_after_filter(db: Database, sample_docs: list[Document]) -> None:
    from datetime import datetime, timezone

    await db.upsert_documents(sample_docs)
    cutoff = datetime(2025, 2, 10, tzinfo=timezone.utc)
    results = await hybrid_search(db, "dark mode", after=cutoff, semantic=False)
    for r in results:
        if r.document.updated_at is not None:
            assert r.document.updated_at >= cutoff


@pytest.mark.asyncio
async def test_excerpt_present(db: Database, sample_docs: list[Document]) -> None:
    await db.upsert_documents(sample_docs)
    results = await keyword_search(db, "CSS variables")
    for r in results:
        assert isinstance(r.excerpt, str)
        assert len(r.excerpt) > 0
