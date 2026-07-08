#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cron_verify.py — Async batch audit verification for cron-imported papers.

Extracts the deferred verification logic from scripts/hfpclawer-audit-verify.py
into a proper module, callable from both CLI and Hermes cron.

Typical use:
    from hfpclawer.audit.cron_verify import batch_verify, print_report

    store = get_store()
    cr = get_crossref()
    stats = batch_verify(store, cr)
    print_report(stats, elapsed=5.2)
"""

from __future__ import annotations

import logging
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("hfpclawer.audit.cron_verify")

ARXIV_API_URL = "http://export.arxiv.org/api/query?id_list={arxiv_id}&max_results=1"
CROSSREF_RATE_LIMIT = 1.1  # seconds between Crossref API calls


@dataclass
class VerifyStats:
    """Aggregated statistics from a batch verify run."""

    total: int = 0
    verified_new: int = 0
    already_verified: int = 0
    doi_found: int = 0
    venue_found: int = 0
    retractions: int = 0
    errors: int = 0
    titles_changed: int = 0

    def summary_line(self) -> str:
        return (
            f"total={self.total}, verified_new={self.verified_new}, "
            f"doi={self.doi_found}, venue={self.venue_found}, "
            f"retracted={self.retractions}, title_changed={self.titles_changed}, "
            f"errors={self.errors}"
        )


def _check_retraction(arxiv_id: str, title: str) -> Optional[dict]:
    """Query arXiv API to check if a paper has been withdrawn.

    Returns None on failure, or a dict with keys:
      - retracted: bool
      - title_changed: bool
      - fresh_title: str
    """
    try:
        url = ARXIV_API_URL.format(arxiv_id=arxiv_id)
        req = urllib.request.urlopen(url, timeout=10)
        xml_data = req.read().decode("utf-8")
        root = ET.fromstring(xml_data)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entries = root.findall("a:entry", ns)
        if not entries:
            return None
        entry = entries[0]
        title_el = entry.find("a:title", ns)
        fresh_title = (
            title_el.text.strip().replace("\n", " ")
            if title_el is not None and title_el.text
            else ""
        )
        result = {
            "retracted": fresh_title.startswith("WITHDRAWN"),
            "title_changed": bool(fresh_title) and fresh_title != title[: len(fresh_title)],
            "fresh_title": fresh_title,
        }
        return result
    except Exception as exc:
        logger.warning("[%s] arXiv query failed: %s", arxiv_id, exc)
        return None


def batch_verify(
    store,
    cr,
    since: str = "",
    retraction_only: bool = False,
    force_all: bool = False,
    rate: float = CROSSREF_RATE_LIMIT,
    verbose: bool = False,
) -> VerifyStats:
    """Verify unverified cron-imported papers in batch.

    Args:
        store: PaperStore instance.
        cr: CrossrefClient instance.
        since: Only verify papers created after this date (YYYY-MM-DD).
        retraction_only: Skip Crossref, only check retractions.
        force_all: Re-verify all cron papers regardless of verified status.
        rate: Seconds between Crossref API calls (default 1.1).
        verbose: Print per-paper progress to logger.info.

    Returns:
        VerifyStats dataclass.
    """
    stats = VerifyStats()

    with store._conn() as conn:
        if force_all:
            rows = conn.execute(
                "SELECT sf_id, title FROM papers WHERE source LIKE 'cron:%'"
            ).fetchall()
        elif since:
            rows = conn.execute(
                """SELECT sf_id, title FROM papers
                   WHERE source LIKE 'cron:%' AND created_at >= ?
                   ORDER BY created_at DESC""",
                (since,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT sf_id, title FROM papers
                   WHERE source LIKE 'cron:%' AND verified = 0
                   ORDER BY created_at DESC LIMIT 500"""
            ).fetchall()

    stats.total = len(rows)

    for row in rows:
        sf_id = row["sf_id"]
        title = row["title"]

        ids = store.get_identifiers(sf_id)
        arxiv_id = next(
            (id_rec.id_value for id_rec in ids if id_rec.id_type == "arxiv"),
            None,
        )
        if not arxiv_id or not title:
            continue

        # ── Retraction check ──
        retraction = _check_retraction(arxiv_id, title)
        if retraction:
            if retraction["retracted"]:
                stats.retractions += 1
                logger.warning("RETRACTED: [%s] %s", arxiv_id, retraction["fresh_title"][:60])
            if retraction["title_changed"]:
                stats.titles_changed += 1
                logger.info("TITLE CHANGED: [%s] old=%s new=%s",
                            arxiv_id, title[:60], retraction["fresh_title"][:60])

        if retraction_only:
            continue

        # ── Crossref cross-verify ──
        try:
            result = cr.cross_verify(arxiv_id, title)
        except Exception as exc:
            stats.errors += 1
            logger.warning("[%s] Crossref verify failed: %s", arxiv_id, exc)
            time.sleep(rate)
            continue

        if result and result.get("doi"):
            doi = result["doi"]
            store.add_identifier(
                sf_id, "doi", doi,
                source="crossref",
                confidence=result.get("confidence", 0.0),
            )
            stats.doi_found += 1
            stats.verified_new += 1

            if result.get("venue"):
                paper = store.get_paper_by_id(sf_id)
                if paper and not paper.venue:
                    paper.venue = result["venue"]
                    paper.year = result.get("year", 0)
                    store.upsert_paper(paper)
                stats.venue_found += 1

            store.verify_paper(sf_id)
            if verbose:
                logger.info("[%s] verified → DOI=%s venue=%s",
                            arxiv_id, doi, result.get("venue", ""))

        elif result and result.get("error") is None:
            # No DOI found but query succeeded — still mark verified
            store.verify_paper(sf_id)
            stats.verified_new += 1

        # Crossref API rate limit
        time.sleep(rate)

    return stats


def format_report(stats: VerifyStats, elapsed: float) -> str:
    """Format verify stats as a human-readable string."""
    lines = [
        f"✅ 审核完成 ({elapsed:.1f}s)",
        f"   扫描论文:       {stats.total}",
        f"   新增已验证:     {stats.verified_new}",
        f"   DOI 匹配:       {stats.doi_found}",
        f"   Venue 补全:     {stats.venue_found}",
        f"   撤稿/异常:      {stats.retractions}",
        f"   标题变更:       {stats.titles_changed}",
        f"   错误:           {stats.errors}",
    ]
    return "\n".join(lines)


def format_report_json(stats: VerifyStats, elapsed: float) -> str:
    """Format verify stats as JSON."""
    import json
    return json.dumps({
        "total": stats.total,
        "verified_new": stats.verified_new,
        "already_verified": stats.already_verified,
        "doi_found": stats.doi_found,
        "venue_found": stats.venue_found,
        "retractions": stats.retractions,
        "titles_changed": stats.titles_changed,
        "errors": stats.errors,
        "elapsed_s": round(elapsed, 1),
    }, ensure_ascii=False, indent=2)
