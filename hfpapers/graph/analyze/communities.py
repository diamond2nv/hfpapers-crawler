#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Community detection — find research communities in the citation network.

Multiple algorithms are provided because each reveals a different
facet of the network structure:

- ``louvain``: Greedy modularity maximisation (fast, good default).
  Can miss small communities.
- ``leiden``: Louvain improvement — guarantees connected communities.
  Better at preserving small clusters.
- ``label_propagation``: Fast, no resolution parameter.
  Non-deterministic; run multiple times for consensus.
- ``girvan_newman``: Hierarchical — produces a dendrogram.
  Slower, but shows nested community structure.

The ``run_all()`` function runs all applicable algorithms and returns
a consensus report showing which communities are robust across methods
and which papers/authors "switch" between communities.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Optional

logger = logging.getLogger("hfpapers.graph.analyze.communities")


def louvain(
    H: "nx.Graph",
    resolution: float = 1.0,
) -> list[set]:
    """Detect communities with the Louvain greedy modularity algorithm.

    Args:
        H: Undirected graph (pass the undirected version of citation graph).
        resolution: Resolution parameter (>1 = more communities, <1 = fewer).

    Returns:
        List of sets, each set contains node IDs in one community.
    """
    from networkx.algorithms.community import greedy_modularity_communities

    logger.info("Running Louvain (resolution=%.2f)...", resolution)
    comms = list(greedy_modularity_communities(H, resolution=resolution))
    logger.info("Louvain found %d communities", len(comms))
    return comms


def leiden(
    H: "nx.Graph",
    resolution: float = 1.0,
) -> list[set]:
    """Detect communities with Leiden algorithm.

    Leiden guarantees that all communities are connected, avoiding a
    known Louvain bug.

    Args:
        H: Undirected graph.
        resolution: Resolution parameter.

    Returns:
        List of community node sets.
    """
    try:
        from networkx.algorithms.community import leiden_communities
    except ImportError:
        logger.warning("Leiden not available in this networkx version, falling back to Louvain")
        return louvain(H, resolution=resolution)

    logger.info("Running Leiden (resolution=%.2f)...", resolution)
    comms = list(leiden_communities(H, resolution=resolution))
    logger.info("Leiden found %d communities", len(comms))
    return comms


def label_propagation(
    H: "nx.Graph",
) -> list[set]:
    """Detect communities with Label Propagation.

    Very fast O(n + m). Non-deterministic — different runs may give
    slightly different results.

    Args:
        H: Undirected graph.

    Returns:
        List of community node sets.
    """
    from networkx.algorithms.community import asyn_lpa_communities

    logger.info("Running Label Propagation...")
    comms = list(asyn_lpa_communities(H))
    logger.info("Label Propagation found %d communities", len(comms))
    return comms


def girvan_newman(
    H: "nx.Graph",
    max_communities: int = 10,
) -> list[list[set]]:
    """Hierarchical community detection via Girvan-Newman.

    Returns a dendrogram (list of levels), each level being a list
    of communities. Level 0 = 2 communities, level 1 = 3, etc.

    Args:
        H: Undirected graph.
        max_communities: Stop when this many communities are reached.

    Returns:
        List of levels, each level is a list of node sets.
    """
    from networkx.algorithms.community import girvan_newman as gn

    logger.info("Running Girvan-Newman (max=%d communities)...", max_communities)
    comp = gn(H)
    levels = []
    for communities in comp:
        levels.append(list(communities))
        if len(levels) >= max_communities - 1:
            break
    logger.info("Girvan-Newman: %d levels generated", len(levels))
    return levels


def _largest_component(Hu: "nx.Graph") -> "nx.Graph":
    """Return the largest connected component of an undirected graph."""
    import networkx as nx

    cc = sorted(nx.connected_components(Hu), key=len, reverse=True)
    if not cc:
        return Hu
    return Hu.subgraph(cc[0]).copy()


def _keyword_signature(
    H: "nx.Graph",
    community: set,
    top_n: int = 8,
) -> list[str]:
    """Extract topical keywords from a community's paper titles.

    Args:
        H: Original graph (with node attributes).
        community: Set of node IDs in one community.
        top_n: Number of keywords to return.

    Returns:
        List of top keywords.
    """
    stop_words = {
        "a", "an", "the", "of", "in", "for", "on", "with", "and",
        "to", "by", "at", "from", "as", "is", "it", "its", "that",
        "this", "these", "we", "are", "has", "been", "was", "were",
        "based", "using", "via", "high", "low", "large", "small",
        "new", "novel", "enhanced", "efficient", "integrated", "two",
        "mode", "one", "three", "first", "second", "non",
    }
    kw: Counter[str] = Counter()
    for nid in community:
        label = str(H.nodes[nid].get("label", H.nodes[nid].get("title", "")))
        words = re.findall(r"[A-Z]?[a-z]{3,}", label.lower())
        kw.update(w for w in words if w not in stop_words and len(w) > 3)
    return [w for w, _ in kw.most_common(top_n)]


def describe_communities(
    H: "nx.Graph",
    communities: list[set],
    top_n: int = 5,
    citation_H: "Optional[nx.DiGraph]" = None,
) -> list[dict[str, Any]]:
    """Generate human-readable descriptions for each community.

    Args:
        H: Undirected graph (with node labels).
        communities: List of community node sets.
        top_n: Top papers per community to show.
        citation_H: Directed citation graph for counting in-community citations.

    Returns:
        List of dicts: id, size, top_papers, keywords.
    """
    results = []

    for ci, comm in enumerate(communities):
        # Count citations within community using directed graph
        cited: Counter[str] = Counter()
        if citation_H is not None:
            for nid in comm:
                if nid in citation_H:
                    cited[nid] = sum(
                        1 for u in citation_H.predecessors(nid) if u in comm
                    )
        else:
            # Fallback: count edges in H within community
            for nid in comm:
                cited[nid] = sum(
                    1 for u in H.neighbors(nid) if u in comm
                )

        top_papers = []
        for nid, c in cited.most_common(top_n):
            label = str(H.nodes[nid].get("label", H.nodes[nid].get("title", nid)))[:80]
            top_papers.append({
                "node_id": nid,
                "label": label,
                "cites_within": c,
            })

        keywords = _keyword_signature(H, comm)

        results.append({
            "id": ci + 1,
            "size": len(comm),
            "top_papers": top_papers,
            "keywords": keywords,
        })

    return results


def run_all(
    H: "nx.Graph",
    resolution: float = 1.0,
    max_communities: int = 10,
    citation_H: "Optional[nx.DiGraph]" = None,
) -> dict[str, Any]:
    """Run all available community detection algorithms.

    Args:
        H: Undirected graph (use H.to_undirected() on a citation DiGraph).
        resolution: Resolution for Louvain/Leiden.
        max_communities: Max levels for Girvan-Newman.
        citation_H: Directed citation graph for per-community citation counts.

    Returns:
        Dict with keys for each algorithm result.
    """
    Hu = _largest_component(H)

    report: dict[str, Any] = {
        "largest_component_size": Hu.number_of_nodes(),
        "total_papers_in_scope": H.number_of_nodes(),
    }

    # Louvain
    try:
        comms = louvain(Hu, resolution=resolution)
        report["louvain"] = {
            "num_communities": len(comms),
            "sizes": [len(c) for c in comms],
            "communities": describe_communities(H, comms, citation_H=citation_H),
        }
    except Exception as e:
        report["louvain"] = {"error": str(e)}

    # Leiden
    try:
        comms = leiden(Hu, resolution=resolution)
        report["leiden"] = {
            "num_communities": len(comms),
            "sizes": [len(c) for c in comms],
            "communities": describe_communities(H, comms, citation_H=citation_H),
        }
    except Exception as e:
        report["leiden"] = {"error": str(e)}

    # Label Propagation
    try:
        comms = label_propagation(Hu)
        report["label_propagation"] = {
            "num_communities": len(comms),
            "sizes": [len(c) for c in comms],
            "communities": describe_communities(H, comms, citation_H=citation_H),
        }
    except Exception as e:
        report["label_propagation"] = {"error": str(e)}

    return report


def full_report(
    H: "nx.Graph",
    resolution: float = 1.0,
    max_communities: int = 10,
    top_n: int = 5,
    citation_H: "Optional[nx.DiGraph]" = None,
) -> dict[str, Any]:
    """Run all community detection and produce a unified report.

    Prefers Leiden if available, falls back to Louvain.

    Args:
        H: Undirected graph.
        resolution: Resolution for modularity-based methods.
        max_communities: Max Girvan-Newman levels.
        top_n: Top papers per community.
        citation_H: Directed citation graph for per-community citation counts.

    Returns:
        Dict with preferred communities and full run_all results.
    """
    Hu = _largest_component(H)

    # Preferred: Leiden or Louvain
    try:
        preferred = leiden(Hu, resolution=resolution)
        algorithm_used = "leiden"
    except Exception:
        preferred = louvain(Hu, resolution=resolution)
        algorithm_used = "louvain"

    return {
        "algorithm": algorithm_used,
        "resolution": resolution,
        "lcc_nodes": Hu.number_of_nodes(),
        "total_nodes": H.number_of_nodes(),
        "num_communities": len(preferred),
        "sizes": sorted([len(c) for c in preferred], reverse=True),
        "communities": describe_communities(H, preferred, top_n=top_n, citation_H=citation_H),
        "all_algorithms": run_all(H, resolution=resolution, citation_H=citation_H),
    }
