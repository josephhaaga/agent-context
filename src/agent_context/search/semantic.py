"""Semantic (embedding-based) search using sentence-transformers.

The model is downloaded on first use (~90 MB for the default model).
Embeddings are stored in SQLite as numpy blobs and reused across sessions.
"""

from __future__ import annotations

import asyncio
import functools
from typing import TYPE_CHECKING

import numpy as np

from agent_context.models import Document, SearchResult
from agent_context.storage.database import Database

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

# Default model — small, fast, good quality for English enterprise text
DEFAULT_MODEL = "all-MiniLM-L6-v2"

# Characters to embed: title + first N chars of content
_EMBED_CONTENT_LIMIT = 512


def _text_for_embedding(doc: Document) -> str:
    """Build a compact text representation for embedding."""
    content = doc.content[:_EMBED_CONTENT_LIMIT]
    return f"{doc.title}\n\n{content}".strip()


@functools.lru_cache(maxsize=4)
def _load_model(model_name: str) -> SentenceTransformer:
    """Load (and cache) a SentenceTransformer model.

    Deferred import so the dependency is only loaded when semantic search
    is actually requested.
    """
    try:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "sentence-transformers is required for semantic search. "
            "Install it with: pip install sentence-transformers"
        ) from exc
    return SentenceTransformer(model_name)


async def _embed_texts(texts: list[str], model_name: str) -> np.ndarray:
    """Embed a list of texts in a thread pool to avoid blocking the event loop."""
    loop = asyncio.get_running_loop()
    model = await loop.run_in_executor(None, _load_model, model_name)
    embeddings = await loop.run_in_executor(None, model.encode, texts)
    return np.array(embeddings, dtype=np.float32)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-D vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


async def build_embeddings(
    db: Database,
    model_name: str = DEFAULT_MODEL,
    source: str | None = None,
) -> int:
    """Generate and store embeddings for documents that don't have them yet.

    Args:
        db: Open Database instance.
        model_name: SentenceTransformer model identifier.
        source: Restrict to a single source plugin.

    Returns:
        Number of embeddings generated.
    """
    docs: list[Document] = []
    async for doc in db.get_documents_for_embedding(source=source, missing_only=True):
        docs.append(doc)

    if not docs:
        return 0

    texts = [_text_for_embedding(doc) for doc in docs]
    embeddings = await _embed_texts(texts, model_name)

    for doc, emb in zip(docs, embeddings, strict=True):
        await db.upsert_embedding(doc.id, emb, model_name)

    return len(docs)


async def semantic_search(
    db: Database,
    query: str,
    sources: list[str] | None = None,
    limit: int = 50,
    model_name: str = DEFAULT_MODEL,
    min_score: float = 0.1,
) -> list[SearchResult]:
    """Run semantic similarity search over stored embeddings.

    Args:
        db: Open Database instance.
        query: User query string.
        sources: Optional source filter (applied post-similarity).
        limit: Max results to return.
        model_name: Embedding model to use.
        min_score: Cosine similarity threshold — results below are discarded.

    Returns:
        List of SearchResult sorted by descending semantic score.
    """
    # Embed the query
    query_emb = (await _embed_texts([query], model_name))[0]

    # Load all stored embeddings
    all_embeddings: list[tuple[str, np.ndarray]] = await db.get_all_embeddings(model=model_name)
    if not all_embeddings:
        return []

    # Score each document
    scored: list[tuple[str, float]] = []
    for doc_id, emb in all_embeddings:
        score = _cosine_similarity(query_emb, emb)
        if score >= min_score:
            scored.append((doc_id, score))

    # Sort descending, keep top-limit
    scored.sort(key=lambda x: x[1], reverse=True)
    scored = scored[:limit]

    if not scored:
        return []

    # Fetch the actual documents
    results: list[SearchResult] = []
    for doc_id, score in scored:
        # Apply source filter
        src = doc_id.split(":")[0]
        if sources and src not in sources:
            continue

        doc = await db.get_document(doc_id)
        if doc is None:
            continue

        excerpt = doc.content[:200].strip()
        if len(doc.content) > 200:
            excerpt += "…"

        results.append(
            SearchResult(
                document=doc,
                score=score,
                keyword_score=0.0,
                semantic_score=score,
                excerpt=excerpt,
            )
        )

    return results
