#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sync_back.py — Zotero Favor → paper_store interest signal (roadmap §2b).

Zotero is an OPTIONAL enhancement adapter: Layer 1 (offline recommendation)
never depends on it. When present, Favor-tagged items whose scholarly
identifier (DOI/arXiv) matches a local paper write `favorited=1` — the
interest signal the learned ranker can later consume.

Filter discipline (user constraint, 2026-09-03): Zotero libraries mix books,
web pages, reports and computer programs. ONLY DOI/arXiv-bearing scholarly
items are useful; everything else is dropped before any store lookup.
"""

from __future__ import annotations

from hfpapers.contracts import ZoteroItem


def sync_back(
    client,
    store,
    tag: str = "Favor",
    limit: int = 300,
    mark: bool = True,
) -> dict:
    """Pull tag items from Zotero and favorite matching local papers.

    Returns stats:
      total / scholarly / in_store / newly_favorited /
      skipped_non_scholarly / skipped_not_in_store / errors
    """
    stats = {
        "total": 0,
        "scholarly": 0,
        "in_store": 0,
        "newly_favorited": 0,
        "skipped_non_scholarly": 0,
        "skipped_not_in_store": 0,
        "errors": 0,
    }
    try:
        items = client.items(tag=tag, limit=limit)
    except Exception:
        return stats  # Zotero unreachable → empty stats, never raises

    for item in items or []:
        stats["total"] += 1
        if not isinstance(item, dict):
            stats["errors"] += 1
            continue
        data = item.get("data", item)
        try:
            zitem = ZoteroItem.model_validate(data)
        except Exception:
            stats["errors"] += 1
            continue
        if not zitem.scholarly:
            stats["skipped_non_scholarly"] += 1
            continue
        stats["scholarly"] += 1
        pid = zitem.paper_identifier
        if pid is None:
            stats["skipped_not_in_store"] += 1
            continue
        paper = store.get_paper_by_identifier(pid[0], pid[1])
        if paper is None:
            stats["skipped_not_in_store"] += 1
            continue
        stats["in_store"] += 1
        if mark:
            store.mark_favorited(paper.sf_id)
            stats["newly_favorited"] += 1
    return stats
