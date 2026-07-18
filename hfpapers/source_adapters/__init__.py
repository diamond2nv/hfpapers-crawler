"""
hfpapers.sources — Multi-Source Document Adapters

This package provides adapters for non-arXiv document sources:
patents (CNIPA, USPTO), legal docs, GB standards, GitHub repos.

Each adapter implements BaseSource ABC:
    class BaseSource(ABC):
        name: str
        def search(self, query, limit=10) -> list[SourceDocument]
        def fetch(self, doc_id) -> SourceDocument | None

SourceDocument dataclass is the unified output format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Optional


@dataclass
class SourceDocument:
    """Unified document from any external source
    
    Fields match the existing SearchResult dataclass for paper_store compatibility.
    """
    id: str                    # Source-specific identifier
    title: str
    abstract: str              # Short summary
    content: str               # Full markdown text
    source: str                # "gh_ingest" | "patent_cn" | "patent_us" | "legal_doc" | "standard_gb"
    source_url: str
    authors: str = ""
    year: int = 0
    tags: list[str] = field(default_factory=list)
    doi: str = ""
    code_url: str = ""
    confidence: float = 0.3
    metadata: dict = field(default_factory=dict)  # Extra source-specific data


class BaseSource(ABC):
    """Abstract base source adapter"""
    
    name: str = "base"          # Override in subclass
    
    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[SourceDocument]:
        """Search this source for documents matching query"""
        ...
    
    @abstractmethod
    def fetch(self, doc_id: str) -> SourceDocument | None:
        """Fetch full document by its source-specific ID"""
        ...
    
    def to_search_result(self, doc: SourceDocument) -> "SearchResult":
        """Convert to searcher_registry.SearchResult for paper_store ingestion
        
        Default conversion — override if needed.
        """
        from hfpapers.searcher_registry import SearchResult
        return SearchResult(
            arxiv_id=doc.doi or "",
            title=doc.title,
            abstract=doc.abstract or doc.content[:500],
            source=doc.source,
            source_category="",
            source_url=doc.source_url,
            code_url=doc.code_url,
            venue="",
            doi=doc.doi,
            authors=doc.authors,
            score=0.5,
            confidence=doc.confidence,
        )
    
    def ingest_to_paper_store(self, doc: SourceDocument) -> tuple[int, bool]:
        """Direct convenience: ingest a source document to paper_store
        
        Returns (snowflake_id, is_new)
        """
        from hfpapers.paper_store import ensure_paper
        sr = self.to_search_result(doc)
        return ensure_paper(
            arxiv_id=sr.arxiv_id or None,
            title=sr.title,
            source=sr.source_url,
            abstract=sr.abstract,
            venue=sr.venue,
            code_url=sr.code_url,
            relevance=50 if doc.confidence > 0.5 else 20,
        )


from hfpapers.source_adapters.github_ingest import GitHubSource

# ── Source Registry ──────────────────────────────────
SOURCE_REGISTRY: dict[str, type[BaseSource]] = {
    "gh_ingest": GitHubSource,
}

def get_source(name: str) -> BaseSource | None:
    """Get a source adapter by name"""
    cls = SOURCE_REGISTRY.get(name)
    return cls() if cls else None

def list_sources() -> list[str]:
    """List all registered source names"""
    return sorted(SOURCE_REGISTRY.keys())
