"""Core data models for agent-context."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Document:
    """A single indexed document from any data source."""

    # Identity
    source: str  # 'github', 'google', 'slack'
    source_id: str  # ID within source system (e.g. GitHub issue number, Drive file ID)
    doc_type: str  # 'issue', 'pr', 'wiki', 'doc', 'sheet', 'message', 'thread', etc.

    # Content
    title: str
    content: str  # Full text content, used for indexing

    # Provenance
    url: str | None = None
    author: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Source-specific extra fields
    metadata: dict[str, Any] = field(default_factory=dict)

    # Internal
    indexed_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def id(self) -> str:
        """Stable composite ID."""
        return f"{self.source}:{self.source_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "source_id": self.source_id,
            "doc_type": self.doc_type,
            "title": self.title,
            "content": self.content,
            "url": self.url,
            "author": self.author,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "metadata": self.metadata,
            "indexed_at": self.indexed_at.isoformat(),
        }


@dataclass
class SearchResult:
    """A ranked search result wrapping a Document."""

    document: Document
    score: float  # Combined hybrid score 0.0–1.0
    keyword_score: float = 0.0
    semantic_score: float = 0.0
    excerpt: str = ""  # Highlighted snippet

    def to_dict(self) -> dict[str, Any]:
        d = self.document.to_dict()
        d["score"] = round(self.score, 4)
        d["score_breakdown"] = {
            "keyword": round(self.keyword_score, 4),
            "semantic": round(self.semantic_score, 4),
        }
        d["excerpt"] = self.excerpt
        return d


@dataclass
class SourceStatus:
    """Health and index status for a single plugin/source."""

    name: str
    enabled: bool
    cli_available: bool  # Is the required CLI installed?
    authenticated: bool  # Are credentials present and valid?
    document_count: int = 0
    last_indexed: datetime | None = None
    error: str | None = None  # Last error message if any

    @property
    def healthy(self) -> bool:
        return self.enabled and self.cli_available and self.authenticated and self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "cli_available": self.cli_available,
            "authenticated": self.authenticated,
            "document_count": self.document_count,
            "last_indexed": self.last_indexed.isoformat() if self.last_indexed else None,
            "healthy": self.healthy,
            "error": self.error,
        }


def metadata_to_json(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata, default=str)


def json_to_metadata(s: str | None) -> dict[str, Any]:
    if not s:
        return {}
    return json.loads(s)  # type: ignore[no-any-return]
