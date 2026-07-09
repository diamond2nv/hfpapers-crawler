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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import networkx as nx

from hfpapers.graph.schema import (
    NodeType, EdgeType, KG_VERSION, NODE_STYLE, EDGE_STYLE,
    node_id, person_node_id, paper_node_id,
)
from hfpapers.graph.sources.zotero import parse_zotero_item
from hfpapers.graph.sources.wiki import parse_wiki_people

logger = logging.getLogger("hfpapers.graph")


# ── Build marker ───────────────────────────────────────────────

BUILD_MARKER = "~/.hermes/graph_build_marker.json"


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
        self._person_authority_map: dict[str, str] = {}  # zotero_id → wiki_id

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
        return self.G

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
        self.G.add_node(
            nid,
            type=ntype,
            label=attrs.get("label", nid),
            color=style.get("color", "#888"),
            size=style.get("size", 8),
            **attrs,
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
        """Override Zotero-derived person node attrs with wiki ground truth."""
        for node, data in self.G.nodes(data=True):
            if data.get("type") != NodeType.PERSON:
                continue
            if data.get("is_wiki_known"):
                continue  # Already a wiki person

            # Try to find a matching wiki person by last_name
            last = (data.get("last_name") or "").lower()
            first = (data.get("first_name") or "").lower()
            for wpid, wattrs in self._wiki_persons.items():
                wlast = (wattrs.get("last_name") or "").lower()
                wfirst = (wattrs.get("first_name") or "").lower()
                if last == wlast and (not first or not wfirst or first[:2] == wfirst[:2]):
                    # Merge: redirect this Zotero node to wiki node
                    self._person_authority_map[node] = wpid
                    break

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
