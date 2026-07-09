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
        self._config: dict = {}

    @staticmethod
    def _load_config() -> dict:
        """Load graph section from project config.yaml.

        Returns:
            Dict with graph config keys (wiki_dir, cache_path, default_limit, etc.),
            falling back to sensible defaults for missing entries.
        """
        try:
            from hfpapers.config import load_config
            cfg = load_config()
            return cfg.get("graph", {})
        except Exception:
            return {}

    def _topic_from_title(self, title: str) -> list[str]:
        """Extract topic-like phrases from a paper title.

        Filters out common stop-phrases and returns the most
        substantive 1-3 word phrases.

        Args:
            title: Paper title.

        Returns:
            List of topic phrases (max ``max_title_topics``).
        """
        skip = set(self._config.get("skip_common_phrases", [
            "study of", "analysis of", "on the", "towards",
            "investigation", "enhanced", "novel", "new",
            "review", "survey",
        ]))
        max_topics = self._config.get("max_title_topics", 3)
        topic_from_title = self._config.get("topic_from_title", True)

        if not topic_from_title or not title:
            return []

        import re
        # Split on common delimiters: colon, dash, em-dash, semicolon
        parts = re.split(r"[:;\u2014\u2013-]\s*", title, maxsplit=1)
        # Use the first part (before colon) — usually the main topic
        main_part = parts[0].strip()

        # Extract noun phrases: capitalize words, skip stopwords
        stop_words = {"a", "an", "the", "of", "in", "for", "with",
                      "and", "or", "by", "to", "on", "at", "from",
                      "using", "based", "via", "through", "under"}

        words = main_part.split()
        phrases = []
        current = []
        for w in words:
            clean = w.strip("(),.;:!?")
            if not clean:
                continue
            if clean.lower() not in stop_words:
                current.append(clean)
            else:
                if current:
                    phrases.append(" ".join(current))
                    current = []
        if current:
            phrases.append(" ".join(current))

        # Filter out skip phrases and short phrases
        result = []
        for p in phrases:
            p_lower = p.lower()
            if any(sk in p_lower for sk in skip):
                continue
            if len(p.split()) > 4:
                # Too long — take first 3 words
                p = " ".join(p.split()[:3])
            if len(p) > 2 and p not in result:
                result.append(p)

        return result[:max_topics]
    # ── Build ──────────────────────────────────────────────────

    def build(
        self,
        client=None,
        limit: int = 0,
        force: bool = False,
        wiki_dir: str = "",
        paper_store_client=None,
    ) -> nx.Graph:
        """Build the knowledge graph from all configured sources.

        Args:
            client: ZoteroClient instance (local API on localhost:23119).
            limit: Max Zotero items to process. 0 = use config default.
            force: If True, rebuild from scratch (ignore incremental marker).
            wiki_dir: Path to wiki directory for /people/ pages.
                Empty string = use config default.
            paper_store_client: Optional paper_store client for extra metadata.

        Returns:
            NetworkX Graph object.
        """
        self.G = nx.Graph()
        build_start = time.time()
        last_build = 0 if force else _last_build_time()

        # Load config
        cfg = self._load_config()
        limit = limit or cfg.get("default_limit", 200)
        if not wiki_dir:
            wiki_dir = cfg.get("wiki_dir", "~/wiki")
        self._config = cfg

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

        # ── Phase 5: Geo enrichment (institutions, cities, countries) ──
        geo_enabled = cfg.get("geo", {}).get("enabled", True)
        if geo_enabled:
            self._enrich_geo(cfg.get("geo", {}))

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

                if nodes:
                    ntype = nodes[0][0]
                    nid = nodes[0][1]
                    title = nodes[0][2].get("title", "")

                    # Inject TOPIC nodes from paper titles
                    if title and ntype in (NodeType.PAPER, NodeType.BOOK):
                        topics = self._topic_from_title(title)
                        for topic in topics:
                            tid = node_id(NodeType.TOPIC, topic)
                            self._add_node(NodeType.TOPIC, tid, {"label": topic})
                            self.G.add_edge(
                                nid, tid,
                                type=EdgeType.ABOUT_TOPIC,
                                source="title_auto",
                                tfidf=1.0,
                            )
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
        # Remove keys that are set explicitly to avoid duplicate kwargs
        safe_attrs = {k: v for k, v in attrs.items() if k not in ("type", "label", "color", "size")}
        self.G.add_node(
            nid,
            type=ntype,
            label=attrs.get("label", nid),
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

    # ── Phase 5: Geo enrichment ────────────────────────────────

    def _enrich_geo(self, geo_cfg: dict):
        """Add INSTITUTION, CITY, COUNTRY nodes + edges from wiki affiliations.

        Reads geo config:
          - ``enabled`` (bool): master switch
          - ``cache_path`` (str): path to JSONL geo cache
          - ``use_api`` (bool): enable Nominatim API queries
          - ``institution_city`` (dict): additional curated mappings

        Config defaults to sensible values when missing.
        """
        if not self._wiki_persons:
            logger.info("No wiki persons — skipping geo enrichment")
            return

        from hfpapers.graph.sources.institutions import (
            enrich_graph,
            extract_institutions,
            geocode_institutions,
        )

        cache_path = geo_cfg.get("cache_path", "~/.hermes/geo_cache.jsonl")
        use_api = geo_cfg.get("use_api", False)

        logger.info("Phase 5: Geo enrichment starting...")

        # Step 1: Extract institution names from wiki
        inst_names = extract_institutions(self._wiki_persons)
        if not inst_names:
            logger.info("No institution names found in wiki/people")
            return

        logger.info("Found %d unique institution names", len(inst_names))

        # Step 2: Apply any additional curated mappings from config
        extra_mappings = geo_cfg.get("institution_city", {})
        if extra_mappings:
            from hfpapers.graph.sources.institutions import CURATED_LOOKUP, _norm_key
            for k, v in extra_mappings.items():
                CURATED_LOOKUP[_norm_key(k)] = v
            logger.debug("Added %d extra institution mappings from config", len(extra_mappings))

        # Step 3: Geocode institutions
        geo_data = geocode_institutions(
            inst_names,
            cache_path=cache_path,
            use_api=use_api,
        )
        logger.info("Geocoded %d institutions", len(geo_data))

        # Step 4: Enrich graph
        added = enrich_graph(self.G, geo_data, self._wiki_persons)
        logger.info("Phase 5: Geo enrichment done (+%d nodes)", added)

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

    # ── Import from coc-inverse-agent refs.jsonl ─────────────────────

    def ingest_refs_jsonl(self, jsonl_path: str, tag: str = "coc") -> dict:
        """Import papers from a coc-inverse-agent refs.jsonl file.

        Creates PAPER and PERSON nodes with AUTHOR_OF edges for each entry.
        Skips entries already present in the graph (matched by arxiv_id or doi).

        Args:
            jsonl_path: Path to ``refs.jsonl`` (e.g. from coc-inverse-agent).
            tag: Tag string to add to ``sources`` attribute (e.g. 'coc', 'gsnv').

        Returns:
            Dict with counts: ``{"papers_added": N, "papers_skipped": N, "authors_added": N}``.
        """
        path = Path(jsonl_path).expanduser()
        if not path.exists():
            logger.warning("refs.jsonl not found: %s", path)
            return {"papers_added": 0, "papers_skipped": 0, "authors_added": 0}

        papers_added = 0
        papers_skipped = 0
        authors_added = 0

        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                aid = (entry.get("arxiv_id") or "").strip()
                doi = (entry.get("doi") or "").strip()
                title = (entry.get("title") or "").strip()[:200]

                if not aid and not doi:
                    papers_skipped += 1
                    continue

                # Generate paper node ID
                pid = paper_node_id(arxiv_id=aid, doi=doi)

                # Skip if already in graph
                if pid in self.G:
                    papers_skipped += 1
                    continue

                # Add PAPER node
                self.G.add_node(
                    pid,
                    type=NodeType.PAPER,
                    label=title,
                    arxiv_id=aid,
                    doi=doi,
                    year=entry.get("year", 0),
                    venue=(entry.get("journal") or "")[:80],
                    sources=tag,
                )
                papers_added += 1

                # Extract authors
                authors = entry.get("authors", [])
                for author_str in authors:
                    author_str = author_str.strip()
                    if not author_str:
                        continue
                    parts = [p.strip() for p in author_str.split(",", 1)]
                    if len(parts) == 2:
                        last_name, first_name = parts[0], parts[1]
                    else:
                        last_name = parts[0]
                        first_name = ""

                    ppid = person_node_id(last_name, first_name)
                    if ppid not in self.G:
                        self.G.add_node(
                            ppid,
                            type=NodeType.PERSON,
                            label=f"{last_name}, {first_name}".strip(", ")[:80],
                        )
                        authors_added += 1

                    # AUTHOR_OF edge
                    if not self.G.has_edge(ppid, pid):
                        self.G.add_edge(ppid, pid, type=EdgeType.AUTHOR_OF)

                # Auto-inject TOPIC nodes from title
                for topic in self._topic_from_title(title):
                    tid = node_id(NodeType.TOPIC, topic)
                    if tid not in self.G:
                        self.G.add_node(
                            tid,
                            type=NodeType.TOPIC,
                            label=topic,
                        )
                    if not self.G.has_edge(pid, tid):
                        self.G.add_edge(pid, tid, type=EdgeType.ABOUT_TOPIC)

        result = {
            "papers_added": papers_added,
            "papers_skipped": papers_skipped,
            "authors_added": authors_added,
        }
        logger.info("ingest_refs_jsonl: %s", result)
        return result

    # ── Import citation edges from coc omc_graph.graphml ─────────────

    def ingest_citation_graphml(self, graphml_path: str, tag: str = "coc") -> dict:
        """Import citation edges from a coc-inverse-agent ``omc_graph.graphml``.

        The GraphML should contain CITES / CITED_BY edges between PAPER nodes.

        Args:
            graphml_path: Path to ``omc_graph.graphml``.
            tag: Tag to add to edge ``source`` attribute.

        Returns:
            Dict with counts: ``{"edges_added": N, "nodes_added": N}``.
        """
        path = Path(graphml_path).expanduser()
        if not path.exists():
            logger.warning("Citation GraphML not found: %s", path)
            return {"edges_added": 0, "nodes_added": 0}

        try:
            H = nx.read_graphml(str(path))
        except Exception as e:
            logger.warning("Failed to read citation GraphML: %s", e)
            return {"edges_added": 0, "nodes_added": 0}

        edges_added = 0
        nodes_added = 0

        # Import any new PAPER nodes
        for nid, data in H.nodes(data=True):
            if nid not in self.G:
                label = data.get("title") or data.get("label", nid)
                self.G.add_node(nid, type=NodeType.PAPER, label=str(label)[:200],
                                sources=tag)
                nodes_added += 1

        # Import CITES edges
        for u, v, data in H.edges(data=True):
            edge_type_str = data.get("type", "CITES")
            try:
                et = EdgeType[edge_type_str]
            except KeyError:
                et = EdgeType.CITES

            if u not in self.G:
                label_u = H.nodes[u].get("title") or H.nodes[u].get("label", u) if u in H else u
                self.G.add_node(u, type=NodeType.PAPER, label=str(label_u)[:200], sources=tag)
                nodes_added += 1
            if v not in self.G:
                label_v = H.nodes[v].get("title") or H.nodes[v].get("label", v) if v in H else v
                self.G.add_node(v, type=NodeType.PAPER, label=str(label_v)[:200], sources=tag)
                nodes_added += 1

            if not self.G.has_edge(u, v):
                self.G.add_edge(u, v, type=et, source=tag)
                edges_added += 1

        result = {"edges_added": edges_added, "nodes_added": nodes_added}
        logger.info("ingest_citation_graphml: %s", result)
        return result

    # ── Citation network expansion (S2 API) ────────────────────────

    def expand_citations(
        self,
        seed_arxiv_ids: list[str] | None = None,
        max_depth: int = 2,
        direction: str = "both",
        label_source: str = "s2_expanded",
        max_seeds: int = 10,
    ) -> dict:
        """Expand the graph by walking citations from seed papers via S2 API.

        If no seed_arxiv_ids given, picks the highest-relevance coc papers
        from the graph that have arXiv IDs.

        Args:
            seed_arxiv_ids: arXiv IDs to start expansion from.
            max_depth: Citation walk depth.
            direction: 'references', 'citations', or 'both'.
            label_source: Source tag for new nodes.
            max_seeds: Max seeds to process (0 = all).

        Returns:
            Dict with expansion stats.
        """
        from hfpapers.graph.citation_expander import CitationExpander

        # Auto-select seeds from graph if none given
        if not seed_arxiv_ids:
            seed_arxiv_ids = []
            for nid, data in self.G.nodes(data=True):
                src = data.get("sources", "")
                if "coc" in str(src) and data.get("arxiv_id"):
                    aid = str(data["arxiv_id"]).strip()
                    if aid:
                        seed_arxiv_ids.append(aid)
            logger.info("Auto-selected %d coc seeds from graph", len(seed_arxiv_ids))

        if not seed_arxiv_ids:
            logger.warning("No seed papers found for citation expansion")
            return {"papers_found": 0, "edges_added": 0, "api_calls": 0}

        if max_seeds > 0:
            seed_arxiv_ids = seed_arxiv_ids[:max_seeds]

        expander = CitationExpander()
        result = expander.expand_from_seeds(
            seed_arxiv_ids=seed_arxiv_ids,
            graph=self.G,
            max_depth=max_depth,
            direction=direction,
            label_source=label_source,
        )
        return result
