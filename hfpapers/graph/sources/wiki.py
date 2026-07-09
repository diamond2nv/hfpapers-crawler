#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wiki source parser — extract person nodes from wiki/people/ pages.

Handles multiple wiki page formats:
1. YAML frontmatter (``---`` blocks with ``name:`` or ``orcid:`` fields)
2. Chinese person cards: ``# 人物卡片：Chinese（Pinyin）`` or ``# Name`` H1 headers
3. Table-based metadata extraction from markdown tables

These are authoritative: if a Zotero creator's name matches a wiki person,
the wiki attributes (ORCID, affiliation) override the Zotero-derived ones.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from hfpapers.graph.schema import person_node_id

logger = logging.getLogger("hfpapers.graph.wiki")


# ── Main parser ────────────────────────────────────────────────


def parse_wiki_people(wiki_dir: str | Path = "~/wiki") -> dict[str, dict]:
    """Parse all person markdown files from wiki/people/ directory.

    Supports:
    - YAML frontmatter with ``name:``, ``orcid:``, ``affiliation:``, ``research_interests:``
    - Chinese person cards with ``# 人物卡片：姓名（Pinyin）`` H1 header
    - ``# Name`` H1 header for English names
    - ``| **姓名** | value |`` or ``| **name** | value |`` table rows
    - ``| **ORCID** | value |`` for ORCID extraction

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
        # Skip README and index files
        if md_file.stem.lower() in ("readme", "index", "template"):
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        # Phase 1: YAML frontmatter (existing format)
        fm = _parse_frontmatter(text)
        name = _get_frontmatter_field(fm, "name") if fm else ""

        # Phase 2: If no frontmatter name, extract from H1 header
        if not name:
            name = _extract_name_from_h1(text) or ""

        # Phase 3: Fall back to stem (kebab-case filename)
        if not name:
            name = _kebab_to_name(md_file.stem)

        last, first = _split_name(name)

        pid = person_node_id(last, first)

        # Extract extra metadata from tables in the file body
        orcid = _get_frontmatter_field(fm, "orcid") if fm else ""
        if not orcid:
            orcid = _extract_orcid_from_table(text) or ""

        affiliation = _get_frontmatter_field(fm, "affiliation") if fm else ""
        if not affiliation:
            affiliation = _extract_affiliation_from_table(text) or ""

        research_interests = _get_frontmatter_field(fm, "research_interests") if fm else ""
        if not research_interests:
            research_interests = _extract_field_from_table(text, "research_interests", "研究方向") or ""

        persons[pid] = {
            "label": name,
            "last_name": last,
            "first_name": first,
            "wiki_page": md_file.stem,
            "orcid": orcid,
            "google_scholar": _get_frontmatter_field(fm, "google_scholar") or "",
            "affiliation": affiliation,
            "research_interests": research_interests,
            "is_wiki_known": True,
        }
        logger.debug("Wiki person: %s → %s", name, pid)

    logger.info(
        "Loaded %d wiki persons from %s",
        len(persons), people_dir,
    )
    return persons


# ── Name extraction from H1 headers ────────────────────────────


def _extract_name_from_h1(text: str) -> str | None:
    """Extract person name from H1 header.

    Supported formats (in order of priority):

    1. ``# 人物卡片：ChineseName（Pinyin）`` → priority to ``Pinyin``
    2. ``# 人物卡片：ChineseName`` → ``ChineseName``
    3. ``# Name (Affiliation)`` → ``Name``
    4. ``# First Last`` → ``First Last``

    Returns:
        Extracted name string, or None.
    """
    for line in text.split("\n"):
        line = line.strip()
        if not line.startswith("# "):
            continue

        # Strip the "# " prefix
        h1 = line[2:].strip()

        # Format 1: 人物卡片：ChineseName（Pinyin）
        m = re.match(r"人物卡片[:：]\s*(?:.*?)[（(]([^）)]+)[）)]", h1)
        if m:
            return m.group(1).strip()

        # Format 2: 人物卡片：ChineseName (no pinyin)
        m = re.match(r"人物卡片[:：]\s*(.+)", h1)
        if m:
            return m.group(1).strip()

        # Format 3: Just a name
        return h1

    return None


def _kebab_to_name(stem: str) -> str:
    """Convert a kebab-case filename stem to a name.

    E.g. ``chen-xiangdong`` → ``chen-xiangdong`` (keep as-is for parsing)
    """
    return stem


# ── Table metadata extraction ──────────────────────────────────


def _extract_orcid_from_table(text: str) -> str | None:
    """Extract ORCID from markdown table rows, cleaning markdown links."""
    for line in text.split("\n"):
        line = line.strip()
        # | **ORCID** | [xxxx-xxxx-xxxx-xxxx](https://orcid.org/...) | or | **ORCID** | value |
        m = re.search(r"\|\s*\*{0,2}ORCID\*{0,2}\s*\|\s*(.+?)\s*\|", line)
        if m:
            val = m.group(1).strip()
            # Clean markdown link: [0000-0002-6845-387X](https://...) → 0000-0002-6845-387X
            link_m = re.match(r"\[([^\]]+)\]\(https?://orcid\.org/([^\)]+)\)", val)
            if link_m:
                return link_m.group(2)
            # Plain ORCID: 0000-0003-2337-3232
            m_orcid = re.match(r"\d{4}-\d{4}-\d{4}-\d{3}[0-9X]", val)
            if m_orcid:
                return m_orcid.group(0)
            # Non-public
            if val and val not in ("未公开", "未公开（未在USTC教职页面或论文中标注）"):
                return val
    return None


def _extract_affiliation_from_table(text: str) -> str | None:
    """Extract affiliation from markdown table rows."""
    for line in text.split("\n"):
        line = line.strip()
        # | **单位** | value | or | **机构** | value |
        m = re.search(r"\|\s*\*{0,2}单位\*{0,2}\s*\|\s*(.+?)\s*\|", line)
        if m:
            val = m.group(1).strip()
            if val:
                return val
        m = re.search(r"\|\s*\*{0,2}机构\*{0,2}\s*\|\s*(.+?)\s*\|", line)
        if m:
            val = m.group(1).strip()
            if val:
                return val
    return None


def _extract_field_from_table(text: str, *keys: str) -> str | None:
    """Extract a field from markdown table rows by matching any key.

    Args:
        text: Markdown text.
        *keys: Field labels to search for. First match wins.
    """
    for line in text.split("\n"):
        line = line.strip()
        for key in keys:
            m = re.search(rf"\|\s*\*{{0,2}}{re.escape(key)}\*{{0,2}}\s*\|\s*(.+?)\s*\|", line)
            if m:
                val = m.group(1).strip()
                if val:
                    return val
    return None


# ── Frontmatter parsing (lightweight) ──────────────────────────


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract YAML frontmatter fields as flat string dict.

    Only handles simple ``key: value`` pairs (no nested structures).
    """
    result: dict[str, str] = {}
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


# ── Name splitting ──────────────────────────────────────────────


def _split_name(name: str) -> tuple[str, str]:
    """Split a full name into (last_name, first_name).

    Handles:

    - ``Li Shen`` → (``Shen``, ``Li``) — English "First Last" convention
    - ``Smith, John`` → (``Smith``, ``John``) — "Last, First" convention
    - ``Xiang-Dong Chen`` → (``Chen``, ``Xiang-Dong``) — hyphenated first name
    - ``Chen Xiangdong`` → (``Chen``, ``Xiangdong``) — Chinese "Last First" convention
    - ``陈向东`` → (``陈向东``, ``＂) — Chinese name (no split possible)
    - ``chen-xiangdong`` → (``chen-xiangdong``, ``＂) — kebab-case

    Uses a heuristic: if a space exists, the LAST word is the surname
    (covers both ``First Last`` English and ``Last First`` Chinese pinyin).
    """
    name = name.strip()
    if not name:
        return ("unknown", "")

    # "Last, First" format
    if "," in name:
        parts = name.split(",", 1)
        return parts[0].strip(), parts[1].strip()

    # Single word — use as last_name
    if " " not in name:
        return name, ""

    # Multi-word: last word is the surname
    parts = name.rsplit(" ", 1)
    return parts[1], parts[0]
