#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Graph analytics — centrality, community detection, ego networks, shortest paths.

All functions accept an ``nx.Graph`` and return plain Python objects
(dicts, lists, sets) for easy CLI rendering and JSON serialization.
"""

from __future__ import annotations

import logging

import networkx as nx

logger = logging.getLogger("hfpapers.graph.analyze")


def degree_centrality(G: nx.Graph) -> dict[str, float]:
    """Return degree centrality for all nodes, sorted descending.

    Higher values = more connections (hub researchers / hot papers).
    """
    return dict(sorted(
        nx.degree_centrality(G).items(),
        key=lambda x: -x[1],
    ))


def betweenness_centrality(G: nx.Graph, top_n: int = 20) -> dict[str, float]:
    """Betweenness centrality (bridging researchers / gatekeepers).

    Args:
        G: Graph to analyze.
        top_n: Return only top N by centrality.

    Returns:
        Dict of node_id → betweenness score, sorted descending.
    """
    result = nx.betweenness_centrality(G, weight=None, normalized=True)
    return dict(sorted(result.items(), key=lambda x: -x[1])[:top_n])


def pagerank(G: nx.Graph, top_n: int = 20) -> dict[str, float]:
    """PageRank on the full graph — identifies influential nodes.

    Falls back to degree centrality when scipy (required by nx.pagerank)
    is not available.

    Args:
        G: Graph to analyze.
        top_n: Return only top N by rank.

    Returns:
        Dict of node_id → PageRank score, sorted descending.
    """
    try:
        result = nx.pagerank(G, weight=None)
    except ImportError:
        logger.warning("scipy not available — PageRank falling back to degree centrality")
        result = nx.degree_centrality(G)
    except Exception as e:
        logger.warning("PageRank failed (%s) — falling back to degree centrality", e)
        result = nx.degree_centrality(G)
    return dict(sorted(result.items(), key=lambda x: -x[1])[:top_n])


def louvain_communities(G: nx.Graph) -> list[set[str]]:
    """Community detection using Louvain algorithm.

    Falls back to greedy modularity if Louvain is unavailable.

    Returns:
        List of node-id sets, one per community (largest first).
    """
    try:
        from networkx.algorithms.community import louvain_communities as _algo
    except ImportError:
        logger.info("Louvain unavailable, falling back to greedy modularity")
        from networkx.algorithms.community import greedy_modularity_communities as _algo

    communities = _algo(G, weight=None)
    return sorted(communities, key=len, reverse=True)


def ego_network(G: nx.Graph, node_id: str, depth: int = 1) -> nx.Graph:
    """Extract the ego network (neighbourhood) around a node.

    Args:
        G: Full graph.
        node_id: Centre node.
        depth: Neighbourhood radius (1 = immediate neighbours).

    Returns:
        Subgraph containing the ego and its neighbours.
    """
    if node_id not in G:
        raise KeyError(f"Node '{node_id}' not found in graph")
    return nx.ego_graph(G, node_id, radius=depth)


def shortest_path(G: nx.Graph, source: str, target: str) -> list[str]:
    """Shortest path between two nodes in the graph.

    Args:
        G: Graph.
        source: Starting node ID.
        target: Target node ID.

    Returns:
        List of node IDs along the path.

    Raises:
        ValueError: If source or target not in graph, or no path exists.
    """
    if source not in G:
        raise KeyError(f"Source node '{source}' not found in graph")
    if target not in G:
        raise KeyError(f"Target node '{target}' not found in graph")
    try:
        return nx.shortest_path(G, source=source, target=target)
    except nx.NetworkXNoPath:
        raise ValueError(f"No path between '{source}' and '{target}'")
