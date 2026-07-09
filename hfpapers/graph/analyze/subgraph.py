#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Subgraph selection — extract focused subgraphs from the knowledge graph.

Picks a subset of nodes and edges based on source tags, edge types,
node types, or connectivity. Used by all analyze modules to scope
analysis to a specific domain (e.g. only coc papers).
"""

from __future__ import annotations

import logging
from typing import Optional

import networkx as nx

from hfpapers.graph.schema import EdgeType, NodeType

logger = logging.getLogger("hfpapers.graph.analyze.subgraph")


def by_source(
    G: nx.Graph,
    source: str,
    edge_types: Optional[set[EdgeType]] = None,
    node_types: Optional[set[NodeType]] = None,
) -> nx.Graph:
    """Extract a subgraph built from nodes tagged with a source.

    Args:
        G: Full knowledge graph.
        source: Source tag to filter by (e.g. 'coc', 'zotero').
        edge_types: Only include these edge types. If None, include all.
        node_types: Only include these node types. If None, include all.

    Returns:
        Subgraph with matching nodes + edges between them.

    Example:
        >>> coc = by_source(G, \"coc\")
        >>> coc_papers = by_source(G, \"coc\", node_types={NodeType.PAPER})
    """
    source = source.lower().strip()

    # Select matching nodes
    selected = set()
    for nid, data in G.nodes(data=True):
        srcs = data.get("sources", set())
        if isinstance(srcs, str):
            srcs = {srcs}
        if source in {s.lower().strip() for s in srcs if isinstance(s, str)}:
            nt = data.get("type")
            if node_types is None or nt in node_types:
                selected.add(nid)
        elif source == "all":
            nt = data.get("type")
            if node_types is None or nt in node_types:
                selected.add(nid)

    # Build subgraph
    H = nx.Graph()
    for nid in selected:
        H.add_node(nid, **dict(G.nodes[nid]))

    for u, v, data in G.edges(data=True):
        if u in selected and v in selected:
            et = data.get("type")
            if edge_types is None or et in edge_types:
                H.add_edge(u, v, **dict(data))

    logger.info(
        "Subgraph(source=%s): %d nodes, %d edges",
        source,
        H.number_of_nodes(),
        H.number_of_edges(),
    )
    return H


def citation_subgraph(G: nx.Graph, source: str = "") -> nx.DiGraph:
    """Build a directed citation subgraph from papers in a source.

    Extracts all PAPER nodes tagged with *source*, then returns only
    CITES edges among them as a directed graph.

    Args:
        G: Full knowledge graph.
        source: Source tag (e.g. 'coc'). If empty, uses all PAPER nodes.

    Returns:
        Directed graph: nodes = papers, edges = CITES direction.
    """
    from hfpapers.graph.schema import EdgeType, NodeType

    H = nx.DiGraph()

    for nid, data in G.nodes(data=True):
        if data.get("type") != NodeType.PAPER:
            continue
        if source:
            srcs = data.get("sources", set())
            if isinstance(srcs, str):
                srcs = {srcs}
            if source.lower() not in {s.lower().strip() for s in srcs if isinstance(s, str)}:
                continue
        H.add_node(
            nid,
            label=str(data.get("label", data.get("title", nid)))[:100],
            arxiv=str(data.get("arxiv_id", "")),
            year=str(data.get("year", "")),
            title=str(data.get("title", data.get("label", ""))),
        )

    for u, v, data in G.edges(data=True):
        et = data.get("type")
        if et == EdgeType.CITES and u in H and v in H:
            H.add_edge(u, v)

    logger.info(
        "Citation subgraph(source=%s): %d papers, %d citation edges",
        source or "all",
        H.number_of_nodes(),
        H.number_of_edges(),
    )
    return H


def author_paper_bipartite(
    G: nx.Graph, source: str = ""
) -> tuple[dict, dict]:
    """Build author-to-paper and paper-to-author mappings for a source.

    Args:
        G: Full knowledge graph.
        source: Source tag filter (empty = all papers).

    Returns:
        (author_papers, paper_authors) dicts.
        author_papers: {person_id: {paper_id, ...}}
        paper_authors: {paper_id: {person_id, ...}}
    """
    from hfpapers.graph.schema import EdgeType, NodeType

    # Determine which papers to include
    papers_in_scope: set[str] = set()
    for nid, data in G.nodes(data=True):
        if data.get("type") != NodeType.PAPER:
            continue
        if source:
            srcs = data.get("sources", set())
            if isinstance(srcs, str):
                srcs = {srcs}
            if source.lower() not in {s.lower().strip() for s in srcs if isinstance(s, str)}:
                continue
        papers_in_scope.add(nid)

    author_papers: dict[str, set[str]] = {}
    paper_authors: dict[str, set[str]] = {}

    for u, v, data in G.edges(data=True):
        if data.get("type") != EdgeType.AUTHOR_OF:
            continue
        if G.nodes[u].get("type") == NodeType.PERSON:
            person, paper = u, v
        else:
            person, paper = v, u
        if paper not in papers_in_scope:
            continue

        author_papers.setdefault(person, set()).add(paper)
        paper_authors.setdefault(paper, set()).add(person)

    return author_papers, paper_authors
