#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Actor analysis — identify key authors, prolific authors, and bridge scholars.

Bridge detection finds authors whose papers span multiple research
communities — these are the "diplomatic" cross-network collaborators.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Any, Optional

logger = logging.getLogger("hfpapers.graph.analyze.actors")


def top_authors(
    author_papers: dict[str, set[str]],
    G: "nx.Graph",
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """Rank authors by number of papers in the source scope.

    Args:
        author_papers: {person_id: {paper_id, ...}} mapping.
        G: Full graph (for node labels).
        top_n: Number of results.

    Returns:
        List of dicts: name, num_papers, node_id.
    """
    ranked = sorted(author_papers.items(), key=lambda x: -len(x[1]))
    results = []
    for pid, papers in ranked[:top_n]:  # Avoid duplicate names
        data = G.nodes[pid]
        name = str(data.get("name", data.get("label", pid)))[:50]
        results.append({
            "node_id": pid,
            "name": name,
            "num_papers": len(papers),
        })
    return results


def bridge_authors(
    author_papers: dict[str, set[str]],
    community_membership: dict[str, set[int]],
    G: "nx.Graph",
    min_communities: int = 2,
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """Find authors whose papers span multiple research communities.

    Args:
        author_papers: {person_id: {paper_id, ...}}.
        community_membership: {paper_id: {community_index, ...}}.
        G: Full graph (for labels).
        min_communities: Minimum communities to qualify as bridge.
        top_n: Max results.

    Returns:
        List of dicts: name, num_papers, num_communities, communities, best_paper.
    """
    bridges = []
    for pid, papers in author_papers.items():
        comms: set[int] = set()
        for p in papers:
            if p in community_membership:
                comms.update(community_membership[p])
        if len(comms) >= min_communities:
            data = G.nodes[pid]
            name = str(data.get("name", data.get("label", pid)))[:50]
            bridges.append({
                "node_id": pid,
                "name": name,
                "num_papers": len(papers),
                "num_communities": len(comms),
                "communities": sorted(comms),
                "algorithm": "bridge",
            })

    bridges.sort(key=lambda x: (-x["num_communities"], -x["num_papers"]))
    return bridges[:top_n]


def build_community_membership(
    communities: list[set],
) -> dict[str, set[int]]:
    """Build a paper→community mapping from community detection results.

    Args:
        communities: List of sets, each set contains node IDs.

    Returns:
        Dict: {node_id: {community_index, ...}}
    """
    membership: dict[str, set[int]] = {}
    for ci, comm in enumerate(communities):
        for nid in comm:
            membership.setdefault(nid, set()).add(ci)
    return membership


def full_report(
    author_papers: dict[str, set[str]],
    paper_authors: dict[str, set[str]],
    communities: list[set],
    G: "nx.Graph",
    top_n: int = 20,
) -> dict[str, Any]:
    """Generate a complete actor analysis report.

    Args:
        author_papers: {person_id: {paper_id, ...}}.
        paper_authors: {paper_id: {person_id, ...}}.
        communities: Community detection results.
        G: Full graph (labels).
        top_n: Results per section.

    Returns:
        Dict with keys: prolific_authors, bridge_authors, stats.
    """
    comm_membership = build_community_membership(communities)

    bridge = bridge_authors(
        author_papers, comm_membership, G,
        min_communities=2, top_n=top_n,
    )

    prolific = top_authors(author_papers, G, top_n=top_n)

    return {
        "stats": {
            "total_authors": len(author_papers),
            "bridge_authors": len(bridge),
        },
        "prolific_authors": prolific,
        "bridge_authors": bridge,
    }
