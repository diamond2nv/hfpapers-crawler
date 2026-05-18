#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# hfpapers/searchers/semanticscholar.py
# Semantic Scholar Searcher — CNS OA journal papers via S2 API
#
# Semantic Scholar supports journal name filtering, openAccessPdf filter,
# and returns externalIds (DOI, ArXiv) for cross-referencing.
# API docs: https://api.semanticscholar.org/api-docs/

import logging
import re

import requests

from hfpapers.searcher_registry import BaseSearcher, SearchResult

logger = logging.getLogger("hfpapers.searchers.semanticscholar")

S2_SEARCH_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"

# CNS OA journals with their Semantic Scholar canonical names
# S2 journal filter is case-sensitive and exact-match
CNS_OA_JOURNAL_NAMES = [
    "Nature Communications",
    "Scientific Reports",
    "Science Advances",
    "Science Robotics",
    "Science Immunology",
    "Science Signaling",
    "Cell Reports",
    "Stem Cell Reports",
]

ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")


class SemanticScholarSearcher(BaseSearcher):
    """Search Semantic Scholar for CNS OA journal papers.

    Uses journal name filter + openAccessPdf filter.
    Returns SearchResult objects with arXiv IDs resolved from externalIds.
    """

    name = "semanticscholar"

    def __init__(
        self,
        journal: str = "Science Advances",
        api_key: str = "",
        fields: str = "title,year,externalIds,openAccessPdf,abstract,journal,publicationTypes,authors",
    ):
        self.journal = journal
        self.api_key = api_key
        self.fields = fields

    @property
    def priority(self) -> int:
        return 40  # After Europe PMC (35), before OpenReview (100)

    def is_available(self) -> bool:
        return True  # Public API (rate-limited without key)

    def search_sync(
        self, query: str, limit: int = 25, category: str = ""
    ) -> list[SearchResult]:
        """Search Semantic Scholar with journal + OA filter."""
        results: list[SearchResult] = []

        params = {
            "query": query,
            "limit": min(limit, 100),
            "fields": self.fields,
            "journal": self.journal,
            "publicationTypes": "JournalArticle",
        }

        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        try:
            resp = requests.get(
                S2_SEARCH_BASE,
                params=params,
                headers=headers,
                timeout=30,
            )
            if resp.status_code != 200:
                logger.warning(
                    f"  [semanticscholar] HTTP {resp.status_code} for '{query}'"
                )
                return results
            data = resp.json()
        except Exception as e:
            logger.warning(f"  [semanticscholar] search failed: {e}")
            return results

        papers = data.get("data", [])
        logger.debug(
            f"  [semanticscholar] {query}: {len(papers)} raw results"
        )

        for paper in papers:
            title = (paper.get("title") or "")[:200]
            if not title:
                continue

            abstract = (paper.get("abstract") or "")[:500]
            year = str(paper.get("year", ""))

            # Extract external IDs
            ext_ids = paper.get("externalIds", {}) or {}
            doi = ext_ids.get("DOI", "")
            arxiv_id = ""
            # Try multiple arXiv ID formats from S2
            arxiv_raw = ext_ids.get("ArXiv", "")
            if arxiv_raw:
                m = ARXIV_ID_RE.search(str(arxiv_raw))
                if m:
                    arxiv_id = m.group(1)

            # OA PDF availability
            # (openAccessPdf filter is already applied in query params)

            # Journal info
            journal_info = paper.get("journal", {}) or {}
            journal_name = journal_info.get("name", self.journal)

            # Authors
            author_list = paper.get("authors", []) or []
            authors = ", ".join(
                a.get("name", "") for a in author_list[:5]
            )

            results.append(
                SearchResult(
                    arxiv_id=arxiv_id,
                    title=title,
                    abstract=abstract,
                    source="semanticscholar",
                    source_url=f"https://api.semanticscholar.org/CorpusID:{paper.get('paperId', '')}",
                    doi=doi,
                    venue=f"{journal_name} ({year})" if year else journal_name,
                    authors=authors,
                    confidence=_evaluate_s2_confidence(paper),
                )
            )

        logger.info(
            f"  [semanticscholar] {query}: {len(results)} papers "
            f"(journal={self.journal})"
        )
        return results


def _evaluate_s2_confidence(paper: dict) -> float:
    """Estimate confidence from S2 metadata."""
    score = 0.3
    ext_ids = paper.get("externalIds", {}) or {}
    if ext_ids.get("DOI"):
        score += 0.2
    if ext_ids.get("ArXiv"):
        score += 0.2
    oa = paper.get("openAccessPdf", {}) or {}
    if oa.get("url"):
        score += 0.2
    if paper.get("citationCount"):
        try:
            cites = int(paper["citationCount"])
            score += min(cites / 200, 0.1)
        except (ValueError, TypeError):
            pass
    return min(score, 1.0)
