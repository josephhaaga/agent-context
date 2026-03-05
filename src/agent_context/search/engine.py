"""Hybrid search engine — merges FTS5 keyword and semantic scores.

Score merging uses a configurable linear combination:
    final_score = keyword_weight * keyword_score + semantic_weight * semantic_score

Both sub-scores are normalised to [0, 1] before combining.
"""

from __future__ import annotations

from datetime import datetime

from agent_context.models import SearchResult
from agent_context.search.fts import keyword_search
from agent_context.search.semantic import DEFAULT_MODEL, semantic_search
from agent_context.storage.database import Database

# Default weight split: keyword-heavy, semantic assists ranking
_DEFAULT_KEYWORD_WEIGHT = 0.6
_DEFAULT_SEMANTIC_WEIGHT = 0.4


async def search(
    db: Database,
    query: str,
    *,
    sources: list[str] | None = None,
    limit: int = 20,
    after: datetime | None = None,
    semantic: bool = True,
    keyword_weight: float = _DEFAULT_KEYWORD_WEIGHT,
    semantic_weight: float = _DEFAULT_SEMANTIC_WEIGHT,
    model_name: str = DEFAULT_MODEL,
) -> list[SearchResult]:
    """Perform hybrid search combining keyword (FTS5) and semantic results.

    When ``semantic=False``, only keyword search is used (faster, no model
    download).

    Args:
        db: Open Database instance.
        query: User query string.
        sources: Restrict results to these source names.
        limit: Maximum results to return.
        after: Only include documents updated after this datetime.
        semantic: Whether to include semantic (embedding) search.
        keyword_weight: Weight for keyword score component.
        semantic_weight: Weight for semantic score component.
        model_name: SentenceTransformer model to use for semantic search.

    Returns:
        Ranked list of SearchResult, best first.
    """
    fetch_limit = limit * 3  # over-fetch so we have room after merging/filtering

    # Run keyword search (always)
    kw_results = await keyword_search(db, query, sources=sources, limit=fetch_limit)

    # Optionally run semantic search in parallel
    sem_results: list[SearchResult] = []
    if semantic:
        sem_results = await semantic_search(
            db,
            query,
            sources=sources,
            limit=fetch_limit,
            model_name=model_name,
        )

    # Merge by document ID
    merged: dict[str, SearchResult] = {}

    for r in kw_results:
        merged[r.document.id] = SearchResult(
            document=r.document,
            score=0.0,
            keyword_score=r.keyword_score,
            semantic_score=0.0,
            excerpt=r.excerpt,
        )

    for r in sem_results:
        doc_id = r.document.id
        if doc_id in merged:
            merged[doc_id].semantic_score = r.semantic_score
            # Update excerpt if keyword result had none
            if not merged[doc_id].excerpt:
                merged[doc_id].excerpt = r.excerpt
        else:
            merged[doc_id] = SearchResult(
                document=r.document,
                score=0.0,
                keyword_score=0.0,
                semantic_score=r.semantic_score,
                excerpt=r.excerpt,
            )

    # Compute final scores
    for r in merged.values():
        r.score = keyword_weight * r.keyword_score + semantic_weight * r.semantic_score

    # Filter by `after` date
    results = list(merged.values())
    if after:
        results = [
            r for r in results if r.document.updated_at is None or r.document.updated_at >= after
        ]

    # Sort and truncate
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:limit]
