#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Graph schema — node types, edge types, ID generation, style mapping.

All node/edge types defined here are used by the graph builder
and understood by JSONL export (Subgraph A → hedge Subgraph B).
"""

from __future__ import annotations

import re
from enum import Enum, auto

# ── Schema version for JSONL export ────────────────────────────
KG_VERSION = "0.10.3"


class NodeType(Enum):
    """Types of nodes in the knowledge graph."""
    PERSON = auto()
    PAPER = auto()
    BOOK = auto()
    JOURNAL = auto()
    TOPIC = auto()
    INSTITUTION = auto()
    CITY = auto()
    COUNTRY = auto()


class EdgeType(Enum):
    """Types of edges in the knowledge graph."""
    AUTHOR_OF = auto()
    PUBLISHED_IN = auto()
    ABOUT_TOPIC = auto()
    CO_AUTHOR = auto()
    AFFILIATED_WITH = auto()
    LOCATED_IN = auto()


# ── Node style mapping (for visualization) ─────────────────────
NODE_STYLE = {
    NodeType.PERSON:       {"color": "#4a9eff", "size": 15, "shape": "circle",     "icon": "👤"},
    NodeType.PAPER:        {"color": "#6bcb77", "size": 8,  "shape": "square",     "icon": "📄"},
    NodeType.BOOK:         {"color": "#ffd93d", "size": 9,  "shape": "diamond",    "icon": "📚"},
    NodeType.JOURNAL:      {"color": "#ff6b6b", "size": 10, "shape": "triangle-up","icon": "📰"},
    NodeType.TOPIC:        {"color": "#34d399", "size": 5,  "shape": "cross",      "icon": "🏷️"},
    NodeType.INSTITUTION:  {"color": "#c084fc", "size": 12, "shape": "triangle-up","icon": "🏛"},
    NodeType.CITY:         {"color": "#f472b6", "size": 7,  "shape": "circle",     "icon": "🏙"},
    NodeType.COUNTRY:      {"color": "#fb923c", "size": 8,  "shape": "circle",     "icon": "🌍"},
}

# ── Edge style ─────────────────────────────────────────────────
EDGE_STYLE = {
    EdgeType.AUTHOR_OF:      {"color": "#888", "width": 1,   "label": "author_of"},
    EdgeType.PUBLISHED_IN:   {"color": "#aaa", "width": 1,   "label": "published_in"},
    EdgeType.ABOUT_TOPIC:    {"color": "#4ade80", "width": 0.8, "label": "about_topic"},
    EdgeType.CO_AUTHOR:      {"color": "#60a5fa", "width": 1.5, "label": "co_author"},
    EdgeType.AFFILIATED_WITH:{"color": "#c084fc", "width": 1.2, "label": "affiliated_with"},
    EdgeType.LOCATED_IN:     {"color": "#fb923c", "width": 1,   "label": "located_in"},
}


# ── ID generation ──────────────────────────────────────────────

def _slugify(s: str) -> str:
    """Generate a URL-safe, deterministic slug from any string."""
    s = s.lower().strip()
    s = re.sub(r"[^\w\s\u4e00-\u9fff]", "-", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-") or "unknown"


def node_id(ntype: NodeType, key: str) -> str:
    """Generate a unique, deterministic node ID.

    Format: ``{type_name}:{slugified_key}``

    Examples:
        >>> node_id(NodeType.PERSON, "Li Shen")
        'person:li-shen'
        >>> node_id(NodeType.PAPER, "2501.01934")
        'paper:2501.01934'
        >>> node_id(NodeType.INSTITUTION, "University of Science and Technology of China")
        'institution:university-of-science-and-technology-of-china'
    """
    return f"{ntype.name.lower()}:{_slugify(key)}"


def person_node_id(last_name: str, first_name: str) -> str:
    """Generate a PERSON node ID from author names.

    Uses the full last_name + first 3 chars of first_name.
    For wiki-known persons, the wiki pages define the canonical ID.
    """
    ln = _slugify(last_name) if last_name else "unknown"
    fn = _slugify(first_name[:3]) if first_name else ""
    if fn:
        return f"person:{ln}-{fn}"
    return f"person:{ln}"


def paper_node_id(arxiv_id: str = "", doi: str = "", zotero_key: str = "") -> str:
    """Generate a PAPER node ID, prioritized by availability."""
    if arxiv_id:
        return f"paper:{arxiv_id}"
    if doi:
        return f"paper:doi-{_slugify(doi)}"
    if zotero_key:
        return f"paper:zotero-{zotero_key}"
    return node_id(NodeType.PAPER, zotero_key or "unknown")
