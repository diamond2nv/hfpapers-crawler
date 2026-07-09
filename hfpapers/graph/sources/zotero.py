#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zotero source parser — convert Zotero API items to graph nodes/edges.

Each Zotero item produces:
  - 1 PAPER or BOOK node
  - 1 JOURNAL node (if publicationTitle present)
  - N PERSON nodes (one per creator)
  - M TOPIC nodes (from innovation_tags in extra)
  - AUTHOR_OF edges: PERSON → PAPER/BOOK
  - PUBLISHED_IN edges: PAPER → JOURNAL
  - ABOUT_TOPIC edges: PAPER → TOPIC
"""

from __future__ import annotations

import logging
import re

from hfpapers.graph.schema import (
    EdgeType,
    NodeType,
    node_id,
    paper_node_id,
    person_node_id,
)

logger = logging.getLogger("hfpapers.graph.zotero")


def parse_zotero_item(item: dict) -> tuple[list[tuple], list[tuple]]:
    """Parse one Zotero item into graph nodes and edges.

    Args:
        item: Zotero API item dict (v3 format, from pyzotero).

    Returns:
        (nodes, edges) where each element is:
            nodes: list of (NodeType, id, attrs_dict)
            edges: list of (EdgeType, source_id, target_id, attrs_dict)
    """
    data = item.get("data", {}) or {}
    key = data.get("key", "")
    title = (data.get("title") or "").strip()
    if not title or not key:
        return [], []

    item_type = data.get("itemType", "")
    pub_title = (data.get("publicationTitle") or data.get("bookTitle") or "").strip()
    date = (data.get("date") or "")[:4]  # Just the year
    doi = (data.get("DOI") or "").strip()
    issn = (data.get("ISSN") or "").strip()
    isbn = (data.get("ISBN") or "").strip()
    extra = (data.get("extra") or "").strip()
    creators = data.get("creators") or []
    arxiv_id = _extract_arxiv_id(url=data.get("url", ""), extra=extra)

    nodes: list[tuple] = []
    edges: list[tuple] = []

    year = _parse_year(date)

    # ── Determine node type: PAPER or BOOK ──
    is_book = item_type in ("book", "bookSection", "report", "manuscript")
    ntype = NodeType.BOOK if is_book else NodeType.PAPER

    pid = paper_node_id(arxiv_id=arxiv_id, doi=doi, zotero_key=key)
    nodes.append((ntype, pid, {
        "label": title[:80],
        "title": title,
        "year": year,
        "zotero_key": key,
        "doi": doi,
        "arxiv_id": arxiv_id or "",
        "isbn": isbn,
        "issn": issn if not is_book else "",
        "item_type": item_type,
    }))

    # ── Creators → Person nodes + AUTHOR_OF edges ──
    author_count = min(len(creators), 50)  # Safety cap
    for i in range(author_count):
        creator = creators[i]
        last = (creator.get("lastName") or "").strip()
        first = (creator.get("firstName") or "").strip()
        if not last:
            continue

        pers_id = person_node_id(last, first)
        nodes.append((NodeType.PERSON, pers_id, {
            "label": f"{last}, {first[:30]}",
            "last_name": last,
            "first_name": first,
        }))
        edges.append((EdgeType.AUTHOR_OF, pers_id, pid, {"position": i}))

    # ── Journal node + PUBLISHED_IN edge ──
    if pub_title and not is_book:
        jid = node_id(NodeType.JOURNAL, pub_title)
        nodes.append((NodeType.JOURNAL, jid, {
            "label": pub_title[:60],
            "issn": issn,
        }))
        edges.append((EdgeType.PUBLISHED_IN, pid, jid, {"year": year}))

    # ── Topic nodes from innovation_tags in extra ──
    topics = _extract_innovation_topics(extra)
    for topic in topics:
        tid = node_id(NodeType.TOPIC, topic)
        nodes.append((NodeType.TOPIC, tid, {"label": topic}))
        edges.append((EdgeType.ABOUT_TOPIC, pid, tid, {"tfidf": 1.0}))

    return nodes, edges


# ── Helpers ────────────────────────────────────────────────────


def _parse_year(date_str: str) -> int:
    """Extract year from Zotero date string."""
    if not date_str:
        return 0
    m = re.match(r"(\d{4})", str(date_str))
    return int(m.group(1)) if m else 0


def _extract_arxiv_id(url: str = "", extra: str = "") -> str:
    """Extract arXiv ID from URL or extra field."""
    # Check URL: arxiv.org/abs/XXXX.XXXXX
    m = re.search(r"arxiv\.org/abs/(\d{4}\.\d{4,5})(v\d+)?", url)
    if m:
        return m.group(1)
    # Check extra field for arXiv:XXXX.XXXXX
    m = re.search(r"arXiv:\s*(\d{4}\.\d{4,5})", extra)
    if m:
        return m.group(1)
    return ""


def _extract_innovation_topics(extra: str) -> list[str]:
    """Extract innovation topic keywords from Zotero extra field.

    Looks for lines starting with ``innovation_`` prefix.
    """
    topics: list[str] = []
    if not extra:
        return topics

    for line in extra.split("\n"):
        line = line.strip()
        if line.startswith("innovation_tags:"):
            # Format: "innovation_tags: FNO; PDE; Neural Operator"
            values = line.split(":", 1)[1].strip()
            for v in values.split(";"):
                v = v.strip()
                if v and len(v) > 1:
                    topics.append(v)
        elif line.startswith("innovation_"):
            # Format: "innovation_method: Fourier Neural Operator"
            values = line.split(":", 1)[1].strip()
            for v in values.split(";"):
                v = v.strip()
                if v and len(v) > 1:
                    topics.append(v)

    # Deduplicate while preserving order
    seen = set()
    return [t for t in topics if not (t.lower() in seen or seen.add(t.lower()))]
