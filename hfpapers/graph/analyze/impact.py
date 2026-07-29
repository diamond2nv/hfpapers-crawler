#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Impact analysis — rank papers and authors by citation influence.

Supports multiple ranking algorithms so the user can compare results:

- ``degree``: Simple in-degree (times cited within the network)
  Fast, intuitive. Biased toward older papers.
- ``pagerank``: Eigenvector centrality on the citation graph
  Rewards being cited by important papers. Requires scipy.
- ``hits``: Hubs and Authorities (Kleinberg)
  Separates survey papers (hubs that cite many) from core works
  (authorities that get cited).
- ``betweenness``: Node betweenness centrality
  Papers that bridge sub-communities. Most relevant for finding
  "connector" works.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

logger = logging.getLogger("hfpapers.graph.analyze.impact")


def by_degree(
    H: "nx.DiGraph",
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """Rank papers by in-degree (times cited within the network).

    Args:
        H: Directed citation subgraph (from subgraph.citation_subgraph).
        top_n: Number of results to return.

    Returns:
        List of dicts with keys: node_id, label, cited_by, cites_others, year, arxiv.
    """
    in_deg = dict(H.in_degree())
    out_deg = dict(H.out_degree())

    results = []
    for nid in H.nodes():
        d = H.nodes[nid]
        results.append({
            "node_id": nid,
            "label": d.get("label", "Unknown"),
            "arxiv": d.get("arxiv", ""),
            "year": d.get("year", ""),
            "cited_by": int(in_deg.get(nid, 0)),
            "cites_others": int(out_deg.get(nid, 0)),
            "algorithm": "degree",
        })
    results.sort(key=lambda x: -x["cited_by"])
    return results[:top_n]


def by_pagerank(
    H: "nx.DiGraph",
    top_n: int = 20,
    alpha: float = 0.85,
) -> list[dict[str, Any]]:
    """Rank papers by PageRank importance.

    Args:
        H: Directed citation subgraph.
        top_n: Number of results.
        alpha: Damping factor (Google default 0.85).

    Returns:
        List of dicts with pagerank score.
    """
    try:
        import scipy  # noqa: F401
    except ImportError:
        logger.warning("scipy not available, falling back to degree")
        return by_degree(H, top_n=top_n)

    import networkx as nx  # noqa: F811

    pr = nx.pagerank(H, alpha=alpha)
    results = []
    for nid, score in pr.items():
        d = H.nodes[nid]
        results.append({
            "node_id": nid,
            "label": d.get("label", "Unknown"),
            "arxiv": d.get("arxiv", ""),
            "year": d.get("year", ""),
            "pagerank": round(float(score), 6),
            "algorithm": "pagerank",
        })
    results.sort(key=lambda x: -x["pagerank"])
    return results[:top_n]


def by_hits(
    H: "nx.DiGraph",
    top_n: int = 20,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rank papers by HITS (Hubs and Authorities).

    Args:
        H: Directed citation subgraph.
        top_n: Number of results per list.

    Returns:
        (authorities, hubs) — each a list of dicts.
        Authorities = most cited (core papers).
        Hubs = most citing (survey/review papers).
    """
    try:
        import scipy  # noqa: F401
    except ImportError:
        logger.warning("scipy not available for HITS")
        return by_degree(H, top_n=top_n), by_degree(H, top_n=top_n)

    import networkx as nx  # noqa: F811

    hubs, authorities = nx.hits(H, max_iter=200, normalized=True)

    def _to_list(scores: dict, label: str) -> list[dict]:
        items = []
        for nid, score in scores.items():
            d = H.nodes[nid]
            items.append({
                "node_id": nid,
                "label": d.get("label", "Unknown"),
                "arxiv": d.get("arxiv", ""),
                "year": d.get("year", ""),
                f"{label}_score": round(float(score), 6),
                "algorithm": f"hits_{label}",
            })
        items.sort(key=lambda x: -x[f"{label}_score"])
        return items[:top_n]

    return _to_list(authorities, "authority"), _to_list(hubs, "hub")


def by_betweenness(
    H: "nx.DiGraph",
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """Rank papers by betweenness centrality.

    Measures how often a paper sits on the shortest path between
    other papers — high betweenness = connector/bridge paper.

    Args:
        H: Directed citation subgraph.
        top_n: Number of results.

    Returns:
        List of dicts with betweenness score.
    """
    import networkx as nx  # noqa: F811

    # Use undirected for betweenness (paths can go either direction)
    Hu = H.to_undirected()
    betweenness = nx.betweenness_centrality(Hu, k=min(100, Hu.number_of_nodes()))

    results = []
    for nid, score in betweenness.items():
        d = H.nodes[nid]
        results.append({
            "node_id": nid,
            "label": d.get("label", "Unknown"),
            "arxiv": d.get("arxiv", ""),
            "year": d.get("year", ""),
            "betweenness": round(float(score), 6),
            "algorithm": "betweenness",
        })
    results.sort(key=lambda x: -x["betweenness"])
    return results[:top_n]


def rank_authors_by_citations(
    H: "nx.DiGraph",
    paper_authors: dict[str, set[str]],
    author_papers: dict[str, set[str]],
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """Rank authors by total citations received.

    Sums the in-degree of each author's papers within the citation
    network.

    Args:
        H: Citation subgraph (paper nodes only).
        paper_authors: {paper_id: {author_id, ...}}
        author_papers: {author_id: {paper_id, ...}}
        top_n: Number of results.

    Returns:
        List of dicts with name, total_cites, num_papers.
    """
    in_deg = dict(H.in_degree())
    author_scores: Counter[str] = Counter()

    for paper_id, cites in in_deg.items():
        if cites > 0:
            for author in paper_authors.get(paper_id, set()):
                author_scores[author] += cites

    results = []
    for author_id, total in author_scores.most_common(top_n):
        npapers = len(author_papers.get(author_id, set()))
        results.append({
            "node_id": author_id,
            "total_cites": total,
            "num_papers": npapers,
            "algorithm": "author_impact",
        })
    return results


def full_impact_report(
    H: "nx.DiGraph",
    paper_authors: dict[str, set[str]],
    author_papers: dict[str, set[str]],
    top_n: int = 20,
) -> dict[str, Any]:
    """Run all impact algorithms and return a unified report dict.

    Args:
        H: Directed citation subgraph.
        paper_authors, author_papers: Mappings from subgraph module.
        top_n: Results per section.

    Returns:
        Dict with keys: degree, pagerank, authorities, hubs,
        betweenness, author_impact, stats.
    """
    report = {
        "stats": {
            "total_papers": H.number_of_nodes(),
            "total_citations": H.number_of_edges(),
        },
        "degree": by_degree(H, top_n=top_n),
        "pagerank": by_pagerank(H, top_n=top_n),
        "betweenness": by_betweenness(H, top_n=top_n),
        "author_impact": rank_authors_by_citations(
            H, paper_authors, author_papers, top_n=top_n
        ),
    }

    try:
        auth, hubs = by_hits(H, top_n=top_n)
        report["authorities"] = auth
        report["hubs"] = hubs
    except Exception:
        report["authorities"] = []
        report["hubs"] = []

    return report
