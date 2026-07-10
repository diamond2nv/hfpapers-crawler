#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Citation network expansion via Semantic Scholar API.

Expands the knowledge graph by walking citation and reference
edges outward from seed papers, discovering new related works.

API: Semantic Scholar Graph API v1 (free tier: 100 req/5min)
Docs: https://api.semanticscholar.org/
"""

from __future__ import annotations

import logging
import time
import re

import requests

logger = logging.getLogger("hfpapers.graph.citation_expander")

# ── Rate limiting (free tier: 100 req / 5 min) ─────────────────
S2_BASE = "https://api.semanticscholar.org/graph/v1"
ARXIV_ID_CLEAN = re.compile(r"^(\d{4}\.\d{4,5})")


class CitationExpander:
    """Walk citation/reference edges outward from seed papers via S2 API.

    Usage:
        expander = CitationExpander(api_key="")  # free tier
        results = expander.expand_from_seeds(["2605.03910", "2303.18091"])
    """

    def __init__(self, api_key: str = "", delay: float = 3.5,
                 filter_keywords: list[str] | None = None,
                 filter_authors: list[str] | None = None):
        """
        Args:
            api_key: S2 API key. Empty = free tier (100 req/5min).
            delay: Seconds between requests (default 3.5s for free tier safety).
            filter_keywords: Optional list of keywords — only keep papers matching ANY keyword.
            filter_authors: Optional list of author name fragments — only keep papers matching ANY author.
        """
        self.api_key = api_key
        self.delay = delay
        self.filter_keywords = filter_keywords or []
        self.filter_authors = filter_authors or []
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "hfpclawer/0.11.0 (citation expander)"})
        if api_key:
            self._session.headers["x-api-key"] = api_key
        self._last_request = 0.0

    # ── Rate limiting ──────────────────────────────────────────

    def _rate_limit(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.time()

    def _get(self, url: str, params: dict | None = None, retries: int = 5) -> dict | None:
        self._rate_limit()
        for attempt in range(retries):
            try:
                resp = self._session.get(url, params=params, timeout=30)
                if resp.status_code == 429:
                    sleep_time = 60 * (2 ** attempt)  # exponential: 60s, 120s, 240s...
                    logger.warning("S2 API rate limited — sleeping %ds (attempt %d/%d)",
                                   sleep_time, attempt + 1, retries)
                    time.sleep(sleep_time)
                    continue
                if resp.status_code == 404:
                    return None
                if resp.status_code != 200:
                    logger.debug("S2 API %s: %s", resp.status_code, resp.text[:100])
                    return None
                return resp.json()
            except requests.RequestException as e:
                logger.debug("S2 API request failed: %s", e)
                if attempt < retries - 1:
                    time.sleep(10 * (2 ** attempt))
                    continue
                return None
        return None

    # ── S2 API calls ───────────────────────────────────────────

    def fetch_paper_by_doi(self, doi: str) -> dict | None:
        """Resolve a DOI to paper metadata via S2 API."""
        url = f"{S2_BASE}/paper/DOI:{doi}"
        data = self._get(url, params={"fields": "title,externalIds,venue,year,authors"})
        return data

    def fetch_paper_by_arxiv(self, arxiv_id: str) -> dict | None:
        """Fetch paper metadata by arXiv ID via S2 API."""
        url = f"{S2_BASE}/paper/ArXiv:{arxiv_id}"
        data = self._get(url, params={"fields": "title,externalIds,venue,year,authors"})
        return data

    def fetch_references(self, arxiv_id: str) -> list[dict]:
        """Fetch papers cited BY *arxiv_id* (its reference list)."""
        fields = "title,externalIds,venue,year"
        if self.filter_keywords or self.filter_authors:
            fields += ",authors"
        url = f"{S2_BASE}/paper/ArXiv:{arxiv_id}/references"
        data = self._get(url, params={"limit": 100, "fields": fields})
        if not data:
            return []
        return [r.get("citedPaper", {}) for r in data.get("data", []) if r.get("citedPaper")]

    def fetch_citations(self, arxiv_id: str) -> list[dict]:
        """Fetch papers that CITE *arxiv_id*."""
        fields = "title,externalIds,venue,year"
        if self.filter_keywords or self.filter_authors:
            fields += ",authors"
        url = f"{S2_BASE}/paper/ArXiv:{arxiv_id}/citations"
        data = self._get(url, params={"limit": 100, "fields": fields})
        if not data:
            return []
        return [r.get("citingPaper", {}) for r in data.get("data", []) if r.get("citingPaper")]

    # ── Main expansion entry point ─────────────────────────────

    def expand_from_seeds(
        self,
        seed_arxiv_ids: list[str],
        graph,
        max_depth: int = 2,
        direction: str = "both",
        label_source: str = "s2_expanded",
    ) -> dict:
        """Expand the graph by walking citations from seed papers via S2 API.

        Seeds can be arXiv IDs (e.g. '2405.00137') or DOIs (e.g. '10.1038/...').

        Args:
            seed_arxiv_ids: List of arXiv IDs or DOIs to start from.
            graph: NetworkX graph to expand (modified in-place).
            max_depth: How many hops to walk (1 = immediate neighbors).
            direction: 'references', 'citations', or 'both'.
            label_source: Source tag for new nodes.

        Returns:
            Dict with counts.
        """
        from hfpapers.graph.schema import paper_node_id, NodeType

        stats = {
            "papers_found": 0,
            "edges_added": 0,
            "api_calls": 0,
            "skipped_existing": 0,
            "seeds_processed": 0,
            "no_arxiv_id": 0,
        }

        # Resolve seeds: normalize arXiv IDs and resolve DOIs via S2
        resolved_seeds: list[str] = []
        for entry in seed_arxiv_ids:
            entry = entry.strip()
            if not entry:
                continue
            if entry.startswith("10."):
                # DOI → fetch paper from S2, add it to graph, get arXiv ID
                paper = self.fetch_paper_by_doi(entry)
                stats["api_calls"] += 1
                if paper:
                    nsid = _add_paper(graph, paper, label_source)
                    if nsid:
                        resolved_seeds.append(nsid)
                        # Also extract arXiv ID for BFS frontier
                        ext = paper.get("externalIds") or {}
                        aid = _extract_arxiv(paper)
                        if aid:
                            resolved_seeds.append(aid)
            else:
                clean = _clean_arxiv(entry)
                if clean:
                    resolved_seeds.append(clean)

        # BFS: frontier of arXiv IDs (used for S2 API calls).
        # DOI-only papers are added to the graph but NOT expanded further.
        visited_pids: set[str] = set()
        frontier: list[tuple[str, int]] = []

        for seed in resolved_seeds:
            if seed.startswith("paper:"):
                # PID from _add_paper — already in graph
                if seed not in visited_pids:
                    visited_pids.add(seed)
                    node_data = graph.nodes.get(seed, {})
                    seed_aid = node_data.get("arxiv_id", "")
                    if seed_aid:
                        frontier.append((seed_aid, 0))
            else:
                # arXiv ID — ensure placeholder node exists
                pid = paper_node_id(arxiv_id=seed)
                if pid not in visited_pids:
                    visited_pids.add(pid)
                    frontier.append((seed, 0))
                    if pid not in graph:
                        graph.add_node(pid, type=NodeType.PAPER,
                                       label=seed, arxiv_id=seed,
                                       doi="", sources=label_source)

        while frontier:
            aid, depth = frontier.pop(0)
            if depth >= max_depth:
                continue

            logger.info("  [S2] %s (depth=%d, %d queued)", aid, depth, len(frontier))
            seed_pid = paper_node_id(arxiv_id=aid)

            # ── References (papers cited by this paper) ──────────
            if direction in ("references", "both"):
                refs = self.fetch_references(aid)
                stats["api_calls"] += 1
                for ref in refs or []:
                    if self.filter_keywords or self.filter_authors:
                        if not self._paper_matches_filters(ref):
                            continue
                    ref_pid = _add_paper(graph, ref, label_source)
                    if not ref_pid:
                        stats["no_arxiv_id"] += 1
                        continue
                    if ref_pid in visited_pids:
                        stats["skipped_existing"] += 1
                        continue
                    visited_pids.add(ref_pid)
                    _add_cites(graph, seed_pid, ref_pid)
                    stats["papers_found"] += 1
                    stats["edges_added"] += 1
                    # Only continue BFS if the ref has an arXiv ID
                    ref_aid = _extract_arxiv(ref)
                    if ref_aid:
                        frontier.append((ref_aid, depth + 1))

            # ── Citations (papers citing this paper) ──────────
            if direction in ("citations", "both"):
                cites = self.fetch_citations(aid)
                stats["api_calls"] += 1
                for cite in cites or []:
                    if self.filter_keywords or self.filter_authors:
                        if not self._paper_matches_filters(cite):
                            continue
                    cite_pid = _add_paper(graph, cite, label_source)
                    if not cite_pid:
                        stats["no_arxiv_id"] += 1
                        continue
                    if cite_pid in visited_pids:
                        stats["skipped_existing"] += 1
                        continue
                    visited_pids.add(cite_pid)
                    _add_cites(graph, cite_pid, seed_pid)
                    stats["papers_found"] += 1
                    stats["edges_added"] += 1
                    # Only continue BFS if has arXiv ID
                    cite_aid = _extract_arxiv(cite)
                    if cite_aid:
                        frontier.append((cite_aid, depth + 1))

            stats["seeds_processed"] += 1

        logger.info("Citation expansion complete: %s", stats)
        return stats

    # ── Filtering ────────────────────────────────────────────────

    def _paper_matches_filters(self, paper: dict) -> bool:
        """Check if a paper dict matches keyword and/or author filters.

        Returns True if NO filters are defined. AND logic (all filters must pass).
        """
        if not self.filter_keywords and not self.filter_authors:
            return True

        title = (paper.get("title") or "").lower()

        # Keywords: OR logic (ANY keyword matches)
        if self.filter_keywords:
            kw_match = any(kw.lower() in title for kw in self.filter_keywords)
            if not kw_match:
                return False

        # Authors: OR logic, check author names from S2 response
        if self.filter_authors:
            authors = paper.get("authors", [])
            author_text = " ".join(
                a.get("name", "") for a in authors
            ).lower()
            auth_match = any(
                a.lower() in author_text for a in self.filter_authors
            )
            if not auth_match:
                return False

        return True


# ── Module-level helpers ────────────────────────────────────────


def _clean_arxiv(aid: str) -> str:
    """Normalize arXiv ID (strip version, whitespace)."""
    m = ARXIV_ID_CLEAN.match(aid.strip())
    return m.group(1) if m else ""


def _extract_arxiv(paper: dict) -> str:
    """Extract arXiv ID from S2 paper dict."""
    ext = paper.get("externalIds") or {}
    aid = ext.get("ArXiv", "")
    return _clean_arxiv(aid)


def _extract_doi(paper: dict) -> str:
    """Extract DOI from S2 paper externalIds. Returns normalized DOI or empty string."""
    ext = paper.get("externalIds") or {}
    doi = ext.get("DOI", "")
    if doi:
        return doi.lower().strip()
    return ""


def _add_paper(graph, paper: dict, source: str) -> str | None:
    """Add a PAPER node from S2 API result. Returns node ID or None.

    Uses arXiv ID as primary key; falls back to DOI when available.
    Stores both identifiers as node attributes for cross-lookup.
    """
    from hfpapers.graph.schema import NodeType, paper_node_id

    aid = _extract_arxiv(paper)
    doi = _extract_doi(paper)

    if not aid and not doi:
        return None

    pid = paper_node_id(arxiv_id=aid, doi=doi)
    if pid in graph:
        return pid

    title = (paper.get("title") or "")[:200]
    venue = (paper.get("venue") or "")[:80]
    year = paper.get("year") or 0

    graph.add_node(
        pid,
        type=NodeType.PAPER,
        label=title or aid or doi,
        arxiv_id=aid or "",
        doi=doi or "",
        venue=venue,
        year=year,
        sources=source,
    )
    return pid


def _add_cites(graph, from_pid: str, to_pid: str):
    """Add a CITES edge between two paper nodes by node PID.

    Args:
        from_pid: Source paper node ID (the one doing the citing).
        to_pid: Target paper node ID (the one being cited).
    """
    from hfpapers.graph.schema import EdgeType

    if from_pid in graph and to_pid in graph and not graph.has_edge(from_pid, to_pid):
        graph.add_edge(from_pid, to_pid, type=EdgeType.CITES, source="s2_expanded")
