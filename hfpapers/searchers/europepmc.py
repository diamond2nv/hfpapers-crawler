#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# hfpapers/searchers/europepmc.py
# Europe PMC Searcher — CNS OA journal papers via Europe PMC REST API
#
# Europe PMC covers Nature Communications, Scientific Reports, Cell Reports,
# and other fully OA journals with full-text access.
# API docs: https://europepmc.org/RestfulWebService

import logging

import requests

from hfpapers.searcher_registry import BaseSearcher, SearchResult

logger = logging.getLogger("hfpapers.searchers.europepmc")

EUROPE_PMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

# CNS OA journal name list (used for Europe PMC JOURNAL: filter)
CNS_OA_JOURNALS = [
    "Nature Communications",
    "Scientific Reports",
    "Science Advances",
    "Science Robotics",
    "Science Immunology",
    "Science Signaling",
    "Cell Reports",
    "Stem Cell Reports",
]


class EuropePMCSearcher(BaseSearcher):
    """Search Europe PMC for CNS OA journal papers.

    Supports journal-filtered search with keyword queries.
    Attempts DOI -> arXiv ID cross-reference via Semantic Scholar
    for pipeline compatibility with the arXiv-based dedup system.
    """

    name = "europepmc"

    def __init__(
        self,
        journal: str = "Nature Communications",
        page_size: int = 25,
        crossref_arxiv: bool = True,
    ):
        self.journal = journal
        self.page_size = page_size
        self.crossref_arxiv = crossref_arxiv
        self._arxiv_cache: dict[str, str] = {}  # DOI -> arXiv ID cache

    @property
    def priority(self) -> int:
        return 35  # After arXiv sources (1-15), before OpenReview

    def is_available(self) -> bool:
        return True  # Public API, no key required

    def search_sync(
        self, query: str, limit: int = 25, category: str = ""
    ) -> list[SearchResult]:
        """Search Europe PMC with journal + keyword filter."""
        results: list[SearchResult] = []

        full_query = f'({query}) AND (JOURNAL:"{self.journal}")'
        params = {
            "query": full_query,
            "resultType": "core",
            "pageSize": min(limit, 100),
            "format": "json",
        }

        try:
            resp = requests.get(EUROPE_PMC_BASE, params=params, timeout=30)
            if resp.status_code != 200:
                logger.warning(
                    f"  [europepmc] HTTP {resp.status_code} for '{query}'"
                )
                return results
            data = resp.json()
        except Exception as e:
            logger.warning(f"  [europepmc] search failed: {e}")
            return results

        result_list = data.get("resultList", {}).get("result", [])
        logger.debug(f"  [europepmc] {query}: {len(result_list)} raw results")

        dois_to_resolve: list[str] = []

        for paper in result_list:
            doi = (paper.get("doi") or "").strip()
            title = (paper.get("title") or "")[:200]
            abstract = (paper.get("abstractText") or "")[:500]
            year = paper.get("pubYear", "")
            journal_title = paper.get("journalTitle", "")
            authors = paper.get("authorString", "")
            source_url = paper.get("source", "")

            if not title:
                continue

            if doi:
                dois_to_resolve.append(doi)

            results.append(
                SearchResult(
                    arxiv_id="",  # Filled by cross-ref below
                    title=title,
                    abstract=abstract,
                    source="europepmc",
                    source_url=source_url or "",
                    doi=doi,
                    venue=f"{journal_title} ({year})" if journal_title else year,
                    authors=authors,
                    confidence=_evaluate_confidence(paper),
                )
            )

        # DOI -> arXiv cross-reference (batch)
        if self.crossref_arxiv and dois_to_resolve:
            resolved = _resolve_arxiv_ids(results, dois_to_resolve, self._arxiv_cache)
            if resolved:
                logger.info(
                    f"  [europepmc] DOI->arXiv resolved: {resolved}/{len(dois_to_resolve)}"
                )

        return results


def _evaluate_confidence(paper: dict) -> float:
    """Estimate quality from available metadata."""
    score = 0.3
    if paper.get("doi"):
        score += 0.3
    if paper.get("hasPDF") == "Y":
        score += 0.2
    if paper.get("citedByCount"):
        try:
            cites = int(paper["citedByCount"])
            score += min(cites / 100, 0.2)
        except (ValueError, TypeError):
            pass
    return min(score, 1.0)


def _resolve_arxiv_ids(
    results: list[SearchResult],
    dois: list[str],
    cache: dict[str, str],
) -> int:
    """Resolve DOI -> arXiv ID via Semantic Scholar batch endpoint.

    Updates SearchResult.arxiv_id in-place. Returns count of resolved IDs.
    """
    to_resolve = [d for d in dois if d not in cache]
    if not to_resolve:
        for r in results:
            if r.doi in cache and cache[r.doi]:
                r.arxiv_id = cache[r.doi]
        return sum(1 for d in cache if cache.get(d))

    resolved = 0
    batch_size = 10

    for i in range(0, len(to_resolve), batch_size):
        batch = to_resolve[i : i + batch_size]
        try:
            resp = requests.post(
                "https://api.semanticscholar.org/graph/v1/paper/batch",
                json={"ids": [f"DOI:{d}" for d in batch]},
                params={"fields": "externalIds"},
                timeout=30,
            )
            if resp.status_code != 200:
                for doi in batch:
                    cache.setdefault(doi, "")
                continue

            data = resp.json()
            if not isinstance(data, list):
                for doi in batch:
                    cache.setdefault(doi, "")
                continue

            for j, item in enumerate(data):
                if j >= len(batch):
                    break
                doi = batch[j]
                if not item:
                    cache[doi] = ""
                    continue
                ext_ids = item.get("externalIds", {}) or {}
                arxiv_id = ext_ids.get("ArXiv", "")
                cache[doi] = arxiv_id
                if arxiv_id:
                    resolved += 1
        except Exception:
            for doi in batch:
                cache.setdefault(doi, "")

    # Apply to results
    for r in results:
        if r.doi in cache and cache[r.doi]:
            r.arxiv_id = cache[r.doi]

    return resolved
