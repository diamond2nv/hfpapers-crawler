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
import re
import time

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
        from hfpapers.graph.schema import NodeType, paper_node_id

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


# ── Hub-guided layered expansion (x-algorithm SimClusters inspired) ────────


def _hub_scores(graph, top_n: int = 15, sources_filter: str = "") -> list[tuple[str, float, str]]:
    """Rank PAPER nodes by PageRank + degree (hub score), filtered by sources.

    Args:
        graph: NetworkX graph.
        top_n: How many top papers to return.
        sources_filter: Only rank papers whose sources start with this tag
            (empty = all papers).

    Returns:
        Sorted list of (node_id, score, arxiv_id) tuples.
    """
    from hfpapers.graph.schema import NodeType

    try:
        import networkx as nx

        pr = nx.pagerank(graph, alpha=0.85, max_iter=50)
    except Exception:
        pr = {}

    scored = []
    for nid, data in graph.nodes(data=True):
        if data.get("type") != NodeType.PAPER:
            continue
        src = str(data.get("sources", ""))
        if sources_filter and not src.startswith(sources_filter):
            continue
        aid = str(data.get("arxiv_id", "")).strip()
        if not aid:
            continue
        score = pr.get(nid, 0.0) * 100.0 + float(graph.degree(nid))
        scored.append((nid, score, aid))
    scored.sort(key=lambda x: -x[1])
    return scored[:top_n]


def _score_map(graph, sources_filter: str = "") -> dict[str, tuple[float, int]]:
    """One-pass {arxiv_id.lower(): (hub_score, degree)} for all PAPER nodes.

    Mirrors _hub_scores scoring: PageRank*100 + degree.
    """
    from hfpapers.graph.schema import NodeType

    try:
        import networkx as nx

        pr = nx.pagerank(graph, alpha=0.85, max_iter=50)
    except Exception:
        pr = {}
    result: dict[str, tuple[float, int]] = {}
    for nid, data in graph.nodes(data=True):
        if data.get("type") != NodeType.PAPER:
            continue
        src = str(data.get("sources", ""))
        if sources_filter and not src.startswith(sources_filter):
            continue
        aid = str(data.get("arxiv_id", "")).strip().lower()
        if not aid:
            continue
        score = pr.get(nid, 0.0) * 100.0 + float(graph.degree(nid))
        result[aid] = (round(score, 4), int(graph.degree(nid)))
    return result


class HubGuidedExpander:
    """Layered citation expansion with hub-guided frontier truncation.

    Inspired by xAI x-algorithm SimClusters: instead of blind BFS (which
    explodes exponentially and stalls on API rate limits), expand one layer
    at a time, rank new papers by hub score (PageRank + degree), keep only
    the top-N as the next frontier, and checkpoint after each layer so the
    run can be resumed.
    """

    def __init__(
        self,
        expander: "CitationExpander",
        top_k: int = 15,
        sources_filter: str = "s2_digiecon",
        checkpoint: str = "",
    ):
        """Args:
        expander: Configured CitationExpander (with keywords/delay).
        top_k: Papers kept per layer (frontier size for next layer).
        sources_filter: Sources tag prefix used to pick hub candidates.
        checkpoint: Path to JSON checkpoint file (empty = no checkpoint).
        """
        self.expander = expander
        self.top_k = top_k
        self.sources_filter = sources_filter
        self.checkpoint = checkpoint

    def run(self, graph, seeds: list[str], max_layers: int = 3,
            direction: str = "both", audit_path: str = "") -> dict:
        """Run layered hub-guided expansion.

        Args:
            graph: NetworkX graph (modified in place).
            seeds: arXiv IDs to start from.
            max_layers: How many layers to walk.
            direction: 'references', 'citations', or 'both'.
            audit_path: Optional JSONL path — per-candidate audit trail
                (adopted / features) for rank training (L1) & explainability.

        Returns:
            Dict with per-layer stats and final hub list.
        """
        import json
        import os
        import time

        frontier = list(seeds)
        start_layer = 0
        if self.checkpoint and os.path.exists(self.checkpoint):
            try:
                with open(self.checkpoint) as f:
                    state = json.load(f)
                frontier = state.get("frontier", frontier)
                start_layer = int(state.get("layer", 0))
            except (OSError, ValueError, KeyError):
                pass

        audit_rows: list[dict] = []
        layers = []
        for layer in range(start_layer + 1, max_layers + 1):
            t0 = time.time()
            stats = self.expander.expand_from_seeds(
                seed_arxiv_ids=frontier,
                graph=graph,
                max_depth=1,
                direction=direction,
                label_source="s2_hub",
            )
            top = _hub_scores(graph, top_n=self.top_k,
                              sources_filter=self.sources_filter)
            adopted = {aid for _, _, aid in top}
            # Per-candidate audit trail (layer L): adopted vs truncated
            candidates = stats.get("papers_found", [])
            if isinstance(candidates, dict):
                candidates = list(candidates.keys()) if candidates else []
            if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
                candidates = [str(c.get("arxiv_id") or c.get("id") or "") for c in candidates]
            # Single-pass score map (avoid per-candidate pagerank recompute)
            score_map = _score_map(graph, sources_filter=self.sources_filter)
            for cand_aid in candidates:
                if not cand_aid:
                    continue
                score, degree = score_map.get(str(cand_aid).strip().lower(), (0.0, 0))
                audit_rows.append({
                    "layer": layer,
                    "arxiv_id": cand_aid,
                    "adopted": cand_aid in adopted,
                    "hub_score": round(score, 4) if score else 0.0,
                    "degree": degree,
                    "seed_depth": 1,
                    "source": "s2_hub",
                })
            layer_stat = {
                "layer": layer,
                "papers_found": stats.get("papers_found", 0) if not isinstance(stats.get("papers_found"), list) else len(stats.get("papers_found", [])),
                "api_calls": stats.get("api_calls", 0),
                "elapsed_s": round(time.time() - t0, 1),
                "frontier": [aid for _, _, aid in top],
                "hub": [(aid, round(score, 2))
                        for _, score, aid in top[:8]],
                "audit_count": len(audit_rows),
            }
            layers.append(layer_stat)

            if audit_path and audit_rows:
                with open(audit_path, "w") as f:
                    for row in audit_rows:
                        f.write(json.dumps(row) + "\n")

            if self.checkpoint:
                with open(self.checkpoint, "w") as f:
                    json.dump({"layer": layer, "frontier": layer_stat["frontier"]}, f)

            if not layer_stat["frontier"]:
                break
            frontier = layer_stat["frontier"]

        result = {
            "layers": layers,
            "layers_completed": len(layers),
            "max_layers": max_layers,
            "final_nodes": graph.number_of_nodes(),
            "final_edges": graph.number_of_edges(),
            "top_hub": layers[-1]["hub"] if layers else [],
        }
        if audit_path:
            result["audit_path"] = audit_path
        return result
