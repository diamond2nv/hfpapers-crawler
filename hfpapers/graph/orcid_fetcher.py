#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ORCID API fetcher — retrieve researcher's publications by ORCID.

Queries the public ORCID API (https://pub.orcid.org/v3.0/) to fetch
all works for a given ORCID iD. Returns structured paper metadata
including DOIs, arXiv IDs (if resolvable), titles, and years.

Free tier: no API key needed, rate limit ~1 req/s (no strict enforcement).
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger("hfpapers.graph.orcid_fetcher")

ORCID_API = "https://pub.orcid.org/v3.0/{orcid}/works"
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "hfpclawer/0.11.0 (orcid seed fetcher)",
}


def fetch_orcid_works(orcid: str, delay: float = 1.0) -> list[dict]:
    """Fetch all published works for an ORCID iD.

    Args:
        orcid: ORCID identifier (e.g. '0000-0001-6559-8101').
        delay: Seconds between API calls (default 1.0).

    Returns:
        List of dicts with keys: doi, arxiv_id, title, year, journal.

    Raises:
        requests.RequestException on network failure.
    """
    url = ORCID_API.format(orcid=orcid)
    resp = requests.get(url, headers=HEADERS, timeout=30)

    if resp.status_code == 404:
        logger.warning("ORCID %s not found", orcid)
        return []
    if resp.status_code == 429:
        logger.warning("ORCID rate limited — sleeping 60s")
        time.sleep(60)
        return fetch_orcid_works(orcid, delay)
    if resp.status_code != 200:
        logger.warning("ORCID API %s: %s", resp.status_code, resp.text[:200])
        return []

    data = resp.json()
    works = []
    for group in data.get("group", []):
        for summary in group.get("work-summary", []):
            work = _parse_work_summary(summary)
            if work:
                works.append(work)

    logger.info("ORCID %s: %d works found", orcid, len(works))
    return works


def _parse_work_summary(summary: dict) -> Optional[dict]:
    """Extract DOI, arXiv ID, title, year from a single work-summary."""
    title = ""
    title_data = summary.get("title", {})
    if "title" in title_data:
        title = (title_data["title"].get("value") or "")

    # Extract DOI from external IDs
    doi = ""
    arxiv_id = ""
    for ext_id in summary.get("external-ids", []):
        ext_type = ext_id.get("external-id-type", "")
        ext_val = ext_id.get("external-id-value", "")
        if ext_type == "doi":
            doi = ext_val.lower().strip()
        elif ext_type in ("arxiv", "arXiv"):
            arxiv_id = ext_val.strip()

    year = 0
    pub_date = summary.get("publication-date", {})
    if pub_date:
        try:
            year_val = pub_date.get("year", {}).get("value")
            if year_val:
                year = int(year_val)
        except (ValueError, TypeError):
            pass

    journal = ""
    journal_data = summary.get("journal-title", {})
    if journal_data:
        journal = journal_data.get("value", "")

    if not title and not doi:
        return None

    return {
        "doi": doi,
        "arxiv_id": arxiv_id,
        "title": title,
        "year": year,
        "journal": journal,
    }


def resolve_doi_to_arxiv(doi: str) -> Optional[str]:
    """Resolve a DOI to arXiv ID via Crossref API.

    Args:
        doi: DOI string (e.g. '10.1038/s41586-022-05335-5').

    Returns:
        arXiv ID string (e.g. '2205.12345') or None.
    """
    url = f"https://api.crossref.org/works/{doi}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        msg = data.get("message", {})
        for link in msg.get("link", []):
            url_str = link.get("url", "")
            if "arxiv.org" in url_str:
                # Extract arXiv ID from URL
                parts = url_str.split("/")
                for p in parts:
                    if len(p) > 5 and "." in p and p[0].isdigit():
                        return _clean_arxiv(p)
        return None
    except requests.RequestException:
        return None


def _clean_arxiv(aid: str) -> str:
    """Normalize arXiv ID (strip version, whitespace)."""
    import re
    m = re.match(r"^(\d{4}\.\d{4,5})", aid.strip())
    return m.group(1) if m else ""
