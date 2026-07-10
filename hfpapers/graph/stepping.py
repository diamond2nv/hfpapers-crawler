#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stepping citation network expansion — multi-layer BFS with config-driven seeds and filters.

Expands a knowledge graph outward from seed papers across defined layers
(QED → Cavity QED → WGM/IQO → OMC → CMM), with per-layer keyword/author
filtering and multi-source seed resolution (arXiv ID, DOI, ORCID).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import networkx as nx
import yaml

from hfpapers.graph.citation_expander import CitationExpander
from hfpapers.graph.config_schema import STEPPING_DEFAULTS, STEPPING_SCHEMA, validate_stepping_config
from hfpapers.graph.orcid_fetcher import fetch_orcid_works, resolve_doi_to_arxiv
from hfpapers.graph.schema import EdgeType, NodeType, paper_node_id

logger = logging.getLogger("hfpapers.graph.stepping")

MARKER_DIR = Path("~/.hermes/step_markers").expanduser()


def _clean_arxiv(aid: str) -> str:
    import re
    m = re.match(r"^(\d{4}\.\d{4,5})", aid.strip())
    return m.group(1) if m else ""


class SteppingExpander:
    """Multi-layer citation network stepper.

    Reads ``stepping`` section from ``config.yaml``, runs each layer
    sequentially, and accumulates results into a single NetworkX Graph.

    Usage::

        stepper = SteppingExpander(config_path="config.yaml")
        G, stats = stepper.run_all()           # full pipeline
        G, stats = stepper.run_layer("wgm")    # single layer
    """

    def __init__(self, config_path: str = "", graph: Optional[nx.Graph] = None):
        self.config_path = Path(config_path or _find_config()).expanduser()
        self.G = graph or self._load_cached_graph()
        self._load_config()

    @staticmethod
    def _load_cached_graph() -> nx.Graph:
        """Load previously saved graph cache, or create empty."""
        from hfpapers.graph import GraphBuilder
        cached = GraphBuilder.load()
        return cached if cached is not None else nx.Graph()

    # ── Config Loading ────────────────────────────────────────────

    def _load_config(self):
        if not self.config_path.exists():
            logger.warning("Config %s not found, using defaults", self.config_path)
            self.config = dict(STEPPING_DEFAULTS)
            return

        with open(self.config_path) as f:
            full_config = yaml.safe_load(f) or {}

        stepping = full_config.get("stepping", {})
        if not stepping or not stepping.get("enabled", True):
            logger.info("Stepping disabled or not configured")
            self.config = dict(STEPPING_DEFAULTS)
            self.config["enabled"] = False
            return

        # Merge with defaults
        merged = dict(STEPPING_DEFAULTS)
        merged.update(stepping)
        self.config = merged
        logger.info("Stepping config loaded: %d layers", len(self.config.get("layers", [])))

    # ── Marker / Resume ───────────────────────────────────────────

    def _marker_path(self, layer_name: str) -> Path:
        return MARKER_DIR / f"{layer_name}.json"

    def _is_completed(self, layer_name: str) -> bool:
        if not self.config.get("resume", True):
            return False
        marker = self._marker_path(layer_name)
        return marker.exists()

    def _save_marker(self, layer_name: str, stats: dict):
        MARKER_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "layer": layer_name,
            "completed_at": time.time(),
            "stats": stats,
        }
        self._marker_path(layer_name).write_text(
            json.dumps(data, indent=2, ensure_ascii=False)
        )

    # ── Seed Resolution ───────────────────────────────────────────

    def _resolve_seeds(self, layer_cfg: dict) -> list[str]:
        """Resolve arXiv IDs, DOIs, and ORCIDs to a flat arXiv ID list."""
        seeds: list[str] = []

        # Direct arXiv IDs / DOIs from 'seeds' list
        for s in layer_cfg.get("seeds", []):
            s = s.strip()
            if not s:
                continue
            if s.startswith("10."):
                # Keep DOI; the expander will resolve it via S2 API
                seeds.append(s)
                logger.info("  DOI seed: %s", s)
            else:
                clean = _clean_arxiv(s)
                if clean:
                    seeds.append(clean)

        # ORCID seed expansion
        for orcid in layer_cfg.get("orcid_seeds", []):
            orcid = orcid.strip()
            if not orcid:
                continue
            logger.info("  Fetching ORCID %s...", orcid)
            try:
                works = fetch_orcid_works(orcid)
            except Exception as e:
                logger.warning("  ORCID fetch failed for %s: %s", orcid, e)
                continue
            for work in works:
                # Prefer arXiv ID, fallback to DOI
                aid = work.get("arxiv_id", "")
                if aid:
                    clean = _clean_arxiv(aid)
                    if clean:
                        seeds.append(clean)
                        continue
                doi = work.get("doi", "")
                if doi:
                    resolved = resolve_doi_to_arxiv(doi)
                    if resolved:
                        seeds.append(resolved)
                    else:
                        # Pass DOI directly for S2 API resolution
                        seeds.append(doi)

        # Deduplicate
        seen: set[str] = set()
        unique = []
        for aid in seeds:
            if aid not in seen:
                seen.add(aid)
                unique.append(aid)

        if seeds:
            logger.info("  Resolved %d unique seeds from %d total entries", len(unique), len(seeds))
        return unique

    # ── Author / Keyword Filtering ────────────────────────────────

    @staticmethod
    def _matches_filter(paper: dict, filter_keywords: list[str],
                        filter_authors: list[str]) -> bool:
        """Check if a paper dict matches keyword and/or author filters.

        Returns True if NO filters are defined (unfiltered mode).
        When filters are defined, ALL conditions must match (AND logic).
        """
        if not filter_keywords and not filter_authors:
            return True

        title = (paper.get("title") or "").lower()
        abstract = (paper.get("abstract") or "").lower()
        text = title + " " + abstract

        # Keyword check: ANY keyword must match (OR within keywords)
        if filter_keywords:
            kw_match = any(kw.lower() in text for kw in filter_keywords)
            if not kw_match:
                return False

        # Author check: ANY author must match (OR within authors)
        if filter_authors:
            paper_authors = " ".join(
                str(a) for a in paper.get("authors", [])
            ).lower()
            author_strs = [p.get("title", "") for p in paper.get("authors", [])]
            author_text = " ".join(author_strs).lower()
            author_match = any(
                a.lower() in author_text or a.lower() in str(paper.get("venue", "")).lower()
                for a in filter_authors
            )
            # Also check the paper title for author names (some papers mention authors in title)
            if not author_match:
                author_match = any(a.lower() in text for a in filter_authors)

            if not author_match:
                return False

        return True

    # ── Layer Runner ──────────────────────────────────────────────

    def run_layer(self, layer_name: str) -> dict:
        """Execute a single layer's expansion.

        Args:
            layer_name: Name of the layer (must match config).

        Returns:
            Dict with expansion stats.
        """
        if not self.config.get("enabled", True):
            return {"papers_found": 0, "edges_added": 0, "skipped": True}

        layer_cfg = self._find_layer(layer_name)
        if not layer_cfg:
            logger.warning("Layer '%s' not found in config", layer_name)
            return {"error": f"Layer '{layer_name}' not found"}

        if self._is_completed(layer_name):
            logger.info("Layer '%s' already completed, skipping (resume=True)", layer_name)
            return {"papers_found": 0, "edges_added": 0, "resumed": True}

        logger.info("═══ Running layer: %s ═══", layer_name)

        # Resolve seeds
        seeds = self._resolve_seeds(layer_cfg)
        if not seeds:
            logger.warning("No seeds resolved for layer '%s'", layer_name)
            return {"papers_found": 0, "edges_added": 0, "no_seeds": True}

        stats = {"seeds": len(seeds), "layer": layer_name}

        # ── Source A: S2 API ──
        s2_enabled = self.config.get("sources", {}).get("s2_api", True)
        if s2_enabled:
            expander = CitationExpander(
                api_key="",
                delay=self.config.get("api_delay", 3.5),
                filter_keywords=layer_cfg.get("filter_keywords", []),
                filter_authors=layer_cfg.get("filter_authors", []),
            )
            s2_result = expander.expand_from_seeds(
                seed_arxiv_ids=seeds,
                graph=self.G,
                max_depth=layer_cfg.get("max_depth", 1),
                direction=layer_cfg.get("direction", "both"),
                label_source=f"step_{layer_name}",
            )
            stats.update(s2_result)

        # Log layer complete
        logger.info("Layer '%s' complete: %s", layer_name, stats)
        self._save_marker(layer_name, stats)
        return stats

    def run_all(self) -> tuple[nx.Graph, dict[str, dict]]:
        """Execute all layers in order.

        Returns:
            (graph, layer_stats) tuple.
        """
        layer_stats: dict[str, dict] = {}
        for layer_cfg in self.config.get("layers", []):
            name = layer_cfg.get("name", "")
            if not name:
                continue
            layer_stats[name] = self.run_layer(name)

        return self.G, layer_stats

    # ── Helpers ───────────────────────────────────────────────────

    def _find_layer(self, name: str) -> Optional[dict]:
        for layer in self.config.get("layers", []):
            if layer.get("name") == name:
                return layer
        return None

    def stats(self) -> dict:
        """Return aggregated stepping stats."""
        n_papers = sum(
            1 for _, d in self.G.nodes(data=True)
            if d.get("type") == NodeType.PAPER
        )
        n_edges = self.G.number_of_edges()
        layers_done = sorted(
            p.stem for p in MARKER_DIR.glob("*.json")
        )
        return {
            "nodes": self.G.number_of_nodes(),
            "papers": n_papers,
            "edges": n_edges,
            "layers_completed": layers_done,
        }


def _find_config() -> str:
    """Auto-discover config.yaml from common locations."""
    candidates = [
        Path("config.yaml"),
        Path.home() / ".config/hfpclawer/config.yaml",
        Path(__file__).parent.parent.parent / "config.yaml",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "config.yaml"
