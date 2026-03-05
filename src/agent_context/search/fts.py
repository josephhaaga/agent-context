"""FTS5 keyword search wrapper."""

from __future__ import annotations

from agent_context.models import Document, SearchResult
from agent_context.storage.database import Database


def _make_excerpt(content: str, query: str, window: int = 200) -> str:
    """Return a snippet of ``content`` around the first query token match."""
    lower = content.lower()
    for token in query.lower().split():
        idx = lower.find(token)
        if idx != -1:
            start = max(0, idx - window // 2)
            end = min(len(content), idx + window // 2)
            snippet = content[start:end].strip()
            if start > 0:
                snippet = "…" + snippet
            if end < len(content):
                snippet = snippet + "…"
            return snippet
    # No match found — return beginning
    return content[:window].strip() + ("…" if len(content) > window else "")


def _normalize_bm25(scores: list[float]) -> list[float]:
    """Min-max normalize a list of BM25 scores to [0, 1]."""
    if not scores:
        return []
    lo = min(scores)
    hi = max(scores)
    span = hi - lo
    if span == 0:
        return [1.0] * len(scores)
    return [(s - lo) / span for s in scores]


async def keyword_search(
    db: Database,
    query: str,
    sources: list[str] | None = None,
    limit: int = 50,
) -> list[SearchResult]:
    """Run FTS5 keyword search and return normalised SearchResult objects.

    Args:
        db: Open Database instance.
        query: Raw user query string.
        sources: Optional list of source names to restrict results.
        limit: Maximum number of results.

    Returns:
        List of SearchResult sorted by descending keyword score.
    """
    raw: list[tuple[Document, float]] = await db.fts_search(query, sources=sources, limit=limit)
    if not raw:
        return []

    docs, scores = zip(*raw)
    normed = _normalize_bm25(list(scores))

    results = []
    for doc, norm_score in zip(docs, normed):
        excerpt = _make_excerpt(doc.content, query)
        results.append(
            SearchResult(
                document=doc,
                score=norm_score,
                keyword_score=norm_score,
                semantic_score=0.0,
                excerpt=excerpt,
            )
        )

    return results
