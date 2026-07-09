#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wiki source parser — extract person nodes from wiki/people/ pages.

Uses frontmatter from markdown files to build ground-truth PERSON nodes.
These are authoritative: if a Zotero creator's name matches a wiki person,
the wiki attributes (ORCID, affiliation) override the Zotero-derived ones.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from hfpapers.graph.schema import NodeType, person_node_id, node_id

logger = logging.getLogger("hfpapers.graph.wiki")


def parse_wiki_people(wiki_dir: str | Path = "~/wiki") -> dict[str, dict]:
    """Parse all person markdown files from wiki/people/ directory.

    Returns:
        Dict mapping person_node_id → {attrs dict}.
        The attrs dict is merged into any Zotero-derived PERSON node
        with the same ID.
    """
    people_dir = Path(wiki_dir).expanduser() / "people"
    if not people_dir.is_dir():
        logger.warning("wiki/people/ not found at %s", people_dir)
        return {}

    persons: dict[str, dict] = {}
    for md_file in sorted(people_dir.glob("*.md")):
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        fm = _parse_frontmatter(text)
        if not fm:
            continue

        name = _get_frontmatter_field(fm, "name") or md_file.stem
        last, first = _split_name(name)

        pid = person_node_id(last, first)
        persons[pid] = {
            "label": name,
            "last_name": last,
            "first_name": first,
            "wiki_page": md_file.stem,
            "orcid": _get_frontmatter_field(fm, "orcid") or "",
            "affiliation": _get_frontmatter_field(fm, "affiliation") or "",
            "research_interests": _get_frontmatter_field(fm, "research_interests") or "",
            "is_wiki_known": True,
        }
        logger.debug("Wiki person: %s → %s", name, pid)

    logger.info("Loaded %d wiki persons from %s", len(persons), people_dir)
    return persons


# ── Frontmatter parsing (lightweight, no dep on frontmatter libs) ──


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract YAML frontmatter fields as flat string dict.

    Only handles simple key: value pairs (no nested structures).
    """
    result: dict[str, str] = {}
    # Match content between --- markers at start of file
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return result
    body = m.group(1)
    for line in body.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip().strip("\"'")
            if key and value:
                result[key] = value
    return result


def _get_frontmatter_field(fm: dict[str, str], key: str) -> str:
    """Get a frontmatter field, trying common key variants."""
    for variant in (key, key.replace("_", ""), key.replace("_", "-")):
        if variant in fm:
            return fm[variant]
    return ""


def _split_name(name: str) -> tuple[str, str]:
    """Split a full name into (last_name, first_name).

    Handles: "Li Shen" → ("Shen", "Li"),  "Smith, John" → ("Smith", "John")
    """
    name = name.strip()
    if "," in name:
        parts = name.split(",", 1)
        return parts[0].strip(), parts[1].strip()
    parts = name.rsplit(" ", 1)
    if len(parts) == 2:
        return parts[1], parts[0]  # Last, First
    return parts[0], ""
