"""SQLite database layer for agent-context."""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

import aiosqlite
import numpy as np

from agent_context.models import Document, SourceStatus, json_to_metadata, metadata_to_json

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    """Async SQLite wrapper handling documents, FTS, and embeddings."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._apply_schema()

    async def _apply_schema(self) -> None:
        schema = _SCHEMA_PATH.read_text()
        await self._conn.executescript(schema)  # type: ignore[union-attr]
        await self._conn.commit()  # type: ignore[union-attr]

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> "Database":
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError(
                "Database not connected. Use 'async with Database(...)' or call connect()."
            )
        return self._conn

    # ------------------------------------------------------------------
    # Document CRUD
    # ------------------------------------------------------------------

    async def upsert_document(self, doc: Document) -> None:
        """Insert or replace a document (keyed on doc.id)."""
        await self.conn.execute(
            """
            INSERT OR REPLACE INTO documents
                (id, source, source_id, doc_type, title, content, url, author,
                 created_at, updated_at, metadata, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc.id,
                doc.source,
                doc.source_id,
                doc.doc_type,
                doc.title,
                doc.content,
                doc.url,
                doc.author,
                doc.created_at.isoformat() if doc.created_at else None,
                doc.updated_at.isoformat() if doc.updated_at else None,
                metadata_to_json(doc.metadata),
                doc.indexed_at.isoformat(),
            ),
        )
        await self.conn.commit()

    async def upsert_documents(self, docs: list[Document]) -> None:
        """Bulk upsert for efficiency."""
        rows = [
            (
                doc.id,
                doc.source,
                doc.source_id,
                doc.doc_type,
                doc.title,
                doc.content,
                doc.url,
                doc.author,
                doc.created_at.isoformat() if doc.created_at else None,
                doc.updated_at.isoformat() if doc.updated_at else None,
                metadata_to_json(doc.metadata),
                doc.indexed_at.isoformat(),
            )
            for doc in docs
        ]
        await self.conn.executemany(
            """
            INSERT OR REPLACE INTO documents
                (id, source, source_id, doc_type, title, content, url, author,
                 created_at, updated_at, metadata, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        await self.conn.commit()

    async def get_document(self, doc_id: str) -> Document | None:
        async with self.conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)) as cur:
            row = await cur.fetchone()
        return _row_to_document(row) if row else None

    async def delete_source(self, source: str) -> int:
        """Delete all documents for a source. Returns count deleted."""
        async with self.conn.execute(
            "SELECT COUNT(*) FROM documents WHERE source = ?", (source,)
        ) as cur:
            row = await cur.fetchone()
            count = row[0] if row else 0
        await self.conn.execute("DELETE FROM documents WHERE source = ?", (source,))
        await self.conn.commit()
        return count

    async def document_count(self, source: str | None = None) -> int:
        if source:
            async with self.conn.execute(
                "SELECT COUNT(*) FROM documents WHERE source = ?", (source,)
            ) as cur:
                row = await cur.fetchone()
        else:
            async with self.conn.execute("SELECT COUNT(*) FROM documents") as cur:
                row = await cur.fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # FTS search
    # ------------------------------------------------------------------

    async def fts_search(
        self,
        query: str,
        sources: list[str] | None = None,
        limit: int = 50,
    ) -> list[tuple[Document, float]]:
        """Full-text search. Returns (document, bm25_score) pairs."""
        # FTS5 bm25() returns negative values; negate for ascending score
        if sources:
            placeholders = ",".join("?" * len(sources))
            sql = f"""
                SELECT d.*, -bm25(documents_fts) AS score
                FROM documents_fts
                JOIN documents d ON d.rowid = documents_fts.rowid
                WHERE documents_fts MATCH ?
                  AND d.source IN ({placeholders})
                ORDER BY score DESC
                LIMIT ?
            """
            params: list[object] = [_fts_query(query), *sources, limit]
        else:
            sql = """
                SELECT d.*, -bm25(documents_fts) AS score
                FROM documents_fts
                JOIN documents d ON d.rowid = documents_fts.rowid
                WHERE documents_fts MATCH ?
                ORDER BY score DESC
                LIMIT ?
            """
            params = [_fts_query(query), limit]

        results: list[tuple[Document, float]] = []
        async with self.conn.execute(sql, params) as cur:
            async for row in cur:
                doc = _row_to_document(row)
                score = float(row["score"]) if row["score"] else 0.0
                results.append((doc, score))
        return results

    async def get_documents_for_embedding(
        self,
        source: str | None = None,
        missing_only: bool = True,
    ) -> AsyncIterator[Document]:
        """Yield documents that need embeddings generated."""
        if missing_only:
            sql = """
                SELECT d.* FROM documents d
                LEFT JOIN embeddings e ON e.document_id = d.id
                WHERE e.document_id IS NULL
            """
            params_e: list[object] = []
            if source:
                sql += " AND d.source = ?"
                params_e.append(source)
        else:
            sql = "SELECT * FROM documents"
            params_e = []
            if source:
                sql += " WHERE source = ?"
                params_e.append(source)

        async with self.conn.execute(sql, params_e) as cur:
            async for row in cur:
                yield _row_to_document(row)

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def upsert_embedding(self, document_id: str, embedding: np.ndarray, model: str) -> None:
        buf = io.BytesIO()
        np.save(buf, embedding.astype(np.float32))
        blob = buf.getvalue()
        await self.conn.execute(
            """
            INSERT OR REPLACE INTO embeddings (document_id, embedding, model, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (document_id, blob, model, datetime.utcnow().isoformat()),
        )
        await self.conn.commit()

    async def get_all_embeddings(self, model: str | None = None) -> list[tuple[str, np.ndarray]]:
        """Load all embeddings into memory for similarity search."""
        if model:
            sql = "SELECT document_id, embedding FROM embeddings WHERE model = ?"
            params_em: list[object] = [model]
        else:
            sql = "SELECT document_id, embedding FROM embeddings"
            params_em = []

        results: list[tuple[str, np.ndarray]] = []
        async with self.conn.execute(sql, params_em) as cur:
            async for row in cur:
                arr = np.load(io.BytesIO(row["embedding"]))
                results.append((row["document_id"], arr))
        return results

    # ------------------------------------------------------------------
    # Source metadata
    # ------------------------------------------------------------------

    async def update_source_meta(
        self,
        source: str,
        last_error: str | None = None,
    ) -> None:
        count = await self.document_count(source)
        await self.conn.execute(
            """
            INSERT OR REPLACE INTO source_meta (source, last_indexed, document_count, last_error)
            VALUES (?, ?, ?, ?)
            """,
            (source, datetime.utcnow().isoformat(), count, last_error),
        )
        await self.conn.commit()

    async def get_source_meta(self, source: str) -> dict[str, object]:
        async with self.conn.execute(
            "SELECT * FROM source_meta WHERE source = ?", (source,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return {"source": source, "last_indexed": None, "document_count": 0, "last_error": None}
        return dict(row)

    async def get_all_source_meta(self) -> list[dict[str, object]]:
        async with self.conn.execute("SELECT * FROM source_meta") as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _row_to_document(row: aiosqlite.Row) -> Document:
    def _dt(s: str | None) -> datetime | None:
        return datetime.fromisoformat(s) if s else None

    return Document(
        source=row["source"],
        source_id=row["source_id"],
        doc_type=row["doc_type"],
        title=row["title"],
        content=row["content"],
        url=row["url"],
        author=row["author"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
        metadata=json_to_metadata(row["metadata"]),
        indexed_at=_dt(row["indexed_at"]) or datetime.utcnow(),
    )


def _fts_query(q: str) -> str:
    """Escape and prepare a user query for FTS5 MATCH."""
    # Wrap each token in quotes to avoid FTS5 syntax errors from special chars
    tokens = q.split()
    if not tokens:
        return '""'
    return " OR ".join(f'"{t}"' for t in tokens)
