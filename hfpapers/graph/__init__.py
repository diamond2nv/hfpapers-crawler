#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hfpapers.graph — Knowledge Graph Builder.

Builds and exports Subgraph A (academic output: people, papers, books,
journals, topics) from Zotero + wiki/people/ + paper_store sources.
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import networkx as nx

from hfpapers.graph import analyze
from hfpapers.graph.schema import (
    EDGE_STYLE,
    KG_VERSION,
    NODE_STYLE,
    EdgeType,
    NodeType,
    node_id,
    paper_node_id,
    person_node_id,
)
from hfpapers.graph.sources.wiki import parse_wiki_people
from hfpapers.graph.sources.zotero import parse_zotero_item

logger = logging.getLogger("hfpapers.graph")


# ── Build marker ───────────────────────────────────────────────

BUILD_MARKER = "~/.hermes/graph_build_marker.json"
GRAPH_CACHE = "~/.hermes/graph_cache.pkl"


def _last_build_time() -> float:
    """Return timestamp of last successful build, or 0."""
    path = Path(BUILD_MARKER).expanduser()
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return data.get("build_time", 0)
        except Exception:
            return 0
    return 0


def _save_build_marker(metadata: dict):
    """Save build marker for incremental builds."""
    path = Path(BUILD_MARKER).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))


# ── GraphBuilder ───────────────────────────────────────────────


class GraphBuilder:
    """Build and manage the knowledge graph from local data sources.

    Usage:
        builder = GraphBuilder()
        G = builder.build(limit=200)
        builder.stats(G)
        builder.export_jsonl(G, "~/data/kg/subgraph_a.jsonl")
    """

    def __init__(self):
        self.G: nx.Graph = nx.Graph()
        self._wiki_persons: dict[str, dict] = {}

    # ── Build ──────────────────────────────────────────────────

    def build(
        self,
        client=None,
        limit: int = 200,
        force: bool = False,
        wiki_dir: str = "~/wiki",
        paper_store_client=None,
    ) -> nx.Graph:
        """Build the knowledge graph from all configured sources.

        Args:
            client: ZoteroClient instance (local API on localhost:23119).
            limit: Max Zotero items to process.
            force: If True, rebuild from scratch (ignore incremental marker).
            wiki_dir: Path to wiki directory for /people/ pages.
            paper_store_client: Optional paper_store client for extra metadata.

        Returns:
            NetworkX Graph object.
        """
        self.G = nx.Graph()
        build_start = time.time()
        last_build = 0 if force else _last_build_time()

        # ── Phase 1: Wiki persons (ground truth) ──
        self._wiki_persons = parse_wiki_people(wiki_dir)
        for pid, attrs in self._wiki_persons.items():
            self.G.add_node(pid, type=NodeType.PERSON, **attrs)

        # ── Phase 2: Zotero items ──
        if client is None:
            logger.warning("No ZoteroClient provided — skipping Zotero source")
        else:
            self._build_from_zotero(client, limit)
            logger.info("Zotero source done")

        # ── Phase 3: Derive CO_AUTHOR edges ──
        self._derive_coauthor_edges()

        # ── Phase 4: Apply wiki authority (override Zotero person attrs) ──
        self._apply_wiki_authority()

        elapsed = time.time() - build_start
        stats = self.stats(self.G, silent=True)
        _save_build_marker({
            "build_time": time.time(),
            "graph_version": KG_VERSION,
            "n_nodes": stats["n_nodes"],
            "n_edges": stats["n_edges"],
            "elapsed_seconds": round(elapsed, 1),
            "built_at": datetime.now(timezone.utc).isoformat(),
        })

        logger.info(
            "Graph built: %d nodes, %d edges in %.1fs",
            stats["n_nodes"], stats["n_edges"], elapsed,
        )

        # Auto-save to cache
        self.save()
        return self.G

    # ── Persistence ────────────────────────────────────────────

    def save(self, path: str = "") -> str:
        """Save the graph as pickle for fast reload.

        Args:
            path: Optional file path. Defaults to GRAPH_CACHE.

        Returns:
            Path to the written file.
        """
        path = path or GRAPH_CACHE
        path_obj = Path(path).expanduser()
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with open(path_obj, "wb") as f:
            pickle.dump(self.G, f)
        logger.info("Graph saved (%d nodes, %d edges) → %s",
                     self.G.number_of_nodes(), self.G.number_of_edges(), path_obj)
        return str(path_obj)

    @staticmethod
    def load(path: str = "") -> "nx.Graph | None":
        """Load a pickled graph from cache.

        Args:
            path: Optional file path. Defaults to GRAPH_CACHE.

        Returns:
            NetworkX Graph, or None if cache doesn't exist.
        """
        path = path or GRAPH_CACHE
        path_obj = Path(path).expanduser()
        if not path_obj.exists():
            return None
        try:
            with open(path_obj, "rb") as f:
                G = pickle.load(f)
            logger.info("Graph loaded (%d nodes, %d edges) from %s",
                         G.number_of_nodes(), G.number_of_edges(), path_obj)
            return G
        except Exception as e:
            logger.warning("Failed to load graph cache: %s", e)
            return None

    def _build_from_zotero(self, client, limit: int):
        """Fetch Zotero items and add to graph."""
        from hfpclawer.zotero import ZoteroConnectionError

        try:
            check = client.check_connection()
            if not check:
                logger.warning("Zotero not reachable at localhost:23119")
                return
        except ZoteroConnectionError as e:
            logger.warning("Zotero connection failed: %s", e)
            return

        stats = {"items": 0, "nodes": 0, "edges": 0, "skipped_no_title": 0}
        batch_size = 50

        for offset in range(0, limit, batch_size):
            batch = client.top(limit=batch_size, start=offset)
            if not batch:
                break

            for item in batch:
                nodes, edges = parse_zotero_item(item)
                if not nodes:
                    stats["skipped_no_title"] += 1
                    continue

                for ntype, nid, attrs in nodes:
                    self._add_node(ntype, nid, attrs)
                    stats["nodes"] += 1

                for etype, src, tgt, attrs in edges:
                    self.G.add_edge(src, tgt, type=etype, **attrs)
                    stats["edges"] += 1

                stats["items"] += 1

            logger.debug("  Zotero batch: %d/%d items", offset + len(batch), limit)

        logger.info(
            "Zotero: %d items → %d nodes, %d edges (%d skipped)",
            stats["items"], stats["nodes"], stats["edges"], stats["skipped_no_title"],
        )

    def _add_node(self, ntype: NodeType, nid: str, attrs: dict):
        """Add a node, avoiding overwrite of wiki-known person attributes."""
        if nid in self.G.nodes:
            existing = self.G.nodes[nid]
            if existing.get("type") == NodeType.PERSON and existing.get("is_wiki_known"):
                # Wiki authority: only add non-conflicting attrs
                for k, v in attrs.items():
                    if k not in existing or not existing[k]:
                        existing[k] = v
                return
            # For non-person nodes, skip duplicates entirely
            return

        style = NODE_STYLE.get(ntype, {})
        # Pop label from attrs to avoid double-pass with **attrs
        safe_attrs = dict(attrs)
        label = safe_attrs.pop("label", nid)
        self.G.add_node(
            nid,
            type=ntype,
            label=label,
            color=style.get("color", "#888"),
            size=style.get("size", 8),
            **safe_attrs,
        )

    def _derive_coauthor_edges(self):
        """Derive CO_AUTHOR edges from shared papers.

        For each paper with N authors, produce CO_AUTHOR edges between
        the first N authors (cap at 10 to avoid combinatorial explosion).
        """
        # Collect papers and their author lists
        paper_authors: dict[str, list[str]] = {}
        for u, v, data in self.G.edges(data=True):
            if data.get("type") != EdgeType.AUTHOR_OF:
                continue
            paper = v  # Edge is PERSON → PAPER
            person = u
            if paper not in paper_authors:
                paper_authors[paper] = []
            paper_authors[paper].append((person, data.get("position", 0)))

        # For each paper, sort authors by position and connect first N
        coauthor_edges: dict[tuple[str, str], int] = {}
        max_authors = 10
        for paper, authors in paper_authors.items():
            authors.sort(key=lambda x: x[1])
            top_authors = [a[0] for a in authors[:max_authors]]
            for i in range(len(top_authors)):
                for j in range(i + 1, len(top_authors)):
                    key = tuple(sorted([top_authors[i], top_authors[j]]))
                    coauthor_edges[key] = coauthor_edges.get(key, 0) + 1

        for (a, b), count in coauthor_edges.items():
            if self.G.has_node(a) and self.G.has_node(b):
                self.G.add_edge(a, b, type=EdgeType.CO_AUTHOR, count=count)

        logger.debug("Derived %d CO_AUTHOR edges", len(coauthor_edges))

    def _apply_wiki_authority(self):
        """Log potential fuzzy matches between Zotero and wiki persons."""
        wiki_names = {
            (w.get("last_name", "").lower(), w.get("first_name", "")[:2].lower())
            for w in self._wiki_persons.values()
        }
        if not wiki_names:
            return
        unmatched = 0
        for node, data in self.G.nodes(data=True):
            if data.get("type") != NodeType.PERSON:
                continue
            if data.get("is_wiki_known"):
                continue
            last = (data.get("last_name") or "").lower()
            first = (data.get("first_name") or "")[:2].lower()
            if (last, first) in wiki_names:
                unmatched += 1

        if unmatched:
            logger.debug("%d Zotero persons with potential wiki matches (same name, different ID)", unmatched)

    # ── Analyze bridge methods ─────────────────────────────────

    def person_ego(self, person_id: str, depth: int = 1) -> nx.Graph | None:
        """Get ego network around a person node."""
        try:
            return analyze.ego_network(self.G, person_id, depth)
        except KeyError:
            return None

    def communities(self) -> list[set[str]]:
        """Detect communities in the graph."""
        return analyze.louvain_communities(self.G)

    def shortest_path(self, source: str, target: str) -> list[str]:
        """Find shortest path between two nodes."""
        return analyze.shortest_path(self.G, source, target)

    def top_nodes(self, metric: str = "degree", top_n: int = 20) -> dict[str, float]:
        """Get top nodes by centrality metric.

        Args:
            metric: ``degree``, ``betweenness``, or ``pagerank``.
            top_n: Number of results.

        Returns:
            Dict of node_id → score, sorted descending.
        """
        if metric == "degree":
            return dict(list(analyze.degree_centrality(self.G).items())[:top_n])
        elif metric == "betweenness":
            return analyze.betweenness_centrality(self.G, top_n)
        elif metric == "pagerank":
            return analyze.pagerank(self.G, top_n)
        else:
            raise ValueError(f"Unknown metric: {metric} (use degree/betweenness/pagerank)")

    # ── Stats ──────────────────────────────────────────────────

    def stats(self, G: nx.Graph = None, silent: bool = False) -> dict:
        """Compute graph statistics.

        Args:
            G: Graph to analyze. Uses ``self.G`` if None.
            silent: If True, return dict without printing.

        Returns:
            Dict with keys: n_nodes, n_edges, by_type, by_edge_type, density, components.
        """
        G = G or self.G
        n_nodes = G.number_of_nodes()
        n_edges = G.number_of_edges()

        # Count by type
        type_counts: dict[str, int] = {}
        for _, data in G.nodes(data=True):
            nt = data.get("type", "UNKNOWN")
            if isinstance(nt, NodeType):
                nt = nt.name
            type_counts[nt] = type_counts.get(nt, 0) + 1

        edge_type_counts: dict[str, int] = {}
        for _, _, data in G.edges(data=True):
            et = data.get("type", "UNKNOWN")
            if isinstance(et, EdgeType):
                et = et.name
            edge_type_counts[et] = edge_type_counts.get(et, 0) + 1

        result = {
            "graph_version": KG_VERSION,
            "n_nodes": n_nodes,
            "n_edges": n_edges,
            "density": round(2 * n_edges / max(n_nodes * (n_nodes - 1), 1), 6),
            "by_type": dict(sorted(type_counts.items(), key=lambda x: -x[1])),
            "by_edge_type": dict(sorted(edge_type_counts.items(), key=lambda x: -x[1])),
            "n_components": nx.number_connected_components(G),
            "n_isolates": nx.number_of_isolates(G),
        }

        if not silent:
            print(f"\n{'='*50}")
            print(f"  📊 Graph Statistics (v{KG_VERSION})")
            print(f"{'='*50}")
            print(f"  Nodes: {n_nodes}  |  Edges: {n_edges}  |  Density: {result['density']}")
            print(f"  Components: {result['n_components']}  |  Isolates: {result['n_isolates']}")
            print(f"  {'─'*30}")
            for nt, count in result["by_type"].items():
                icon = NODE_STYLE.get(NodeType[nt], {}).get("icon", "•")
                print(f"    {icon} {nt}: {count}")
            print(f"  {'─'*30}")
            for et, count in result["by_edge_type"].items():
                print(f"    {EDGE_STYLE.get(EdgeType[et], {}).get('label', et)}: {count}")

        return result

    # ── Export ─────────────────────────────────────────────────

    def export_jsonl(self, output_path: str, G: nx.Graph = None) -> str:
        """Export the graph as JSONL for hedge Subgraph B import.

        Args:
            output_path: Path to write the JSONL file.
            G: Graph to export. Uses ``self.G`` if None.

        Returns:
            Path to the written file.
        """
        G = G or self.G
        path = Path(output_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)

        written = {"nodes": 0, "edges": 0}
        with open(path, "w", encoding="utf-8") as f:
            # — Nodes —
            for nid, data in G.nodes(data=True):
                ntype = data.get("type", "UNKNOWN")
                if isinstance(ntype, NodeType):
                    ntype = ntype.name
                record = {
                    "kg_version": KG_VERSION,
                    "type": "node",
                    "id": nid,
                    "node_type": ntype,
                    "label": data.get("label", nid)[:80],
                    "attrs": {k: v for k, v in data.items()
                              if k not in ("type", "label", "color", "size")},
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                written["nodes"] += 1

            # — Edges —
            for u, v, data in G.edges(data=True):
                etype = data.get("type", "UNKNOWN")
                if isinstance(etype, EdgeType):
                    etype = etype.name
                record = {
                    "kg_version": KG_VERSION,
                    "type": "edge",
                    "source": u,
                    "target": v,
                    "edge_type": etype,
                    "attrs": {k: v for k, v in data.items() if k != "type"},
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                written["edges"] += 1

        logger.info("Exported JSONL: %d nodes, %d edges → %s",
                     written["nodes"], written["edges"], path)
        return str(path)

    def export_graphml(self, output_path: str, G: nx.Graph = None) -> str:
        """Export the graph as GraphML (for Gephi import).

        Args:
            output_path: Path to write the GraphML file.
            G: Graph to export. Uses ``self.G`` if None.
        """
        G = G or self.G
        path = Path(output_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)

        # Convert enum types to strings for GraphML compatibility
        H = nx.Graph()
        for nid, data in G.nodes(data=True):
            attrs = dict(data)
            if isinstance(attrs.get("type"), NodeType):
                attrs["type"] = attrs["type"].name
            H.add_node(nid, **attrs)

        for u, v, data in G.edges(data=True):
            attrs = dict(data)
            if isinstance(attrs.get("type"), EdgeType):
                attrs["type"] = attrs["type"].name
            H.add_edge(u, v, **attrs)

        nx.write_graphml(H, str(path))
        logger.info("Exported GraphML → %s", path)
        return str(path)
