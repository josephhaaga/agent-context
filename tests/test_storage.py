"""Tests for storage layer (database CRUD)."""

from __future__ import annotations

import pytest

from agent_context.models import Document
from agent_context.storage.database import Database


@pytest.mark.asyncio
async def test_upsert_and_get(db: Database, sample_doc: Document) -> None:
    await db.upsert_document(sample_doc)
    fetched = await db.get_document(sample_doc.id)
    assert fetched is not None
    assert fetched.title == sample_doc.title
    assert fetched.source == "github"


@pytest.mark.asyncio
async def test_upsert_replaces(db: Database, sample_doc: Document) -> None:
    await db.upsert_document(sample_doc)
    modified = Document(
        source=sample_doc.source,
        source_id=sample_doc.source_id,
        doc_type=sample_doc.doc_type,
        title="Updated title",
        content="Updated content",
    )
    await db.upsert_document(modified)
    fetched = await db.get_document(sample_doc.id)
    assert fetched is not None
    assert fetched.title == "Updated title"


@pytest.mark.asyncio
async def test_bulk_upsert(db: Database, sample_docs: list[Document]) -> None:
    await db.upsert_documents(sample_docs)
    count = await db.document_count()
    assert count == len(sample_docs)


@pytest.mark.asyncio
async def test_document_count_by_source(db: Database, sample_docs: list[Document]) -> None:
    await db.upsert_documents(sample_docs)
    gh_count = await db.document_count("github")
    slack_count = await db.document_count("slack")
    assert gh_count == 2
    assert slack_count == 1


@pytest.mark.asyncio
async def test_delete_source(db: Database, sample_docs: list[Document]) -> None:
    await db.upsert_documents(sample_docs)
    deleted = await db.delete_source("github")
    assert deleted == 2
    remaining = await db.document_count()
    assert remaining == len(sample_docs) - 2


@pytest.mark.asyncio
async def test_get_nonexistent(db: Database) -> None:
    result = await db.get_document("github:does_not_exist")
    assert result is None


@pytest.mark.asyncio
async def test_source_meta(db: Database, sample_docs: list[Document]) -> None:
    await db.upsert_documents(sample_docs)
    await db.update_source_meta("github")
    meta = await db.get_source_meta("github")
    assert meta["source"] == "github"
    assert meta["document_count"] == 2
    assert meta["last_indexed"] is not None


@pytest.mark.asyncio
async def test_get_all_source_meta(db: Database, sample_docs: list[Document]) -> None:
    await db.upsert_documents(sample_docs)
    await db.update_source_meta("github")
    await db.update_source_meta("slack")
    metas = await db.get_all_source_meta()
    names = {m["source"] for m in metas}
    assert "github" in names
    assert "slack" in names
