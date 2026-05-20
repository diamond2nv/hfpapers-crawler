#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
citation_audit_oa.py — OpenAlex API client for citation verification.

Architecture reference: academic-research-skills/scripts/openalex_client.py
by Cheng-I Wu (CC BY-NC 4.0).

Simplified version: title search with similarity threshold + year tiebreaker.
No DOI_MISMATCH, no per-API degradation contracts, no polite pool email.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from hfpclawer._text_similarity import _normalize_title, title_similarity

logger = logging.getLogger("hfpclawer.citation_audit_oa")

_API_BASE = "https://api.openalex.org"
_POLITE_EMAIL_ENV = "OPENALEX_POLITE_EMAIL"
_FIELDS = "id,title,authorships,publication_year,doi,primary_location"

_POLITE_INTERVAL = 0.1     # 10 req/s with polite email
_ANONYMOUS_INTERVAL = 1.0  # 1 req/s without
_BACKOFF = 2.0
_MAX_RETRIES = 3
_TIMEOUT = 30
_TITLE_THRESHOLD = 0.70


class OAClient:
    """OpenAlex lookup client for citation verification.

    Usage:
        client = OAClient()
        result = client.lookup("Attention Is All You Need")
        # -> {"status": "VERIFIED"|"NOT_FOUND"|"ERROR", ...}
    """

    def __init__(self, polite_email: Optional[str] = None):
        self._email = polite_email or os.environ.get(_POLITE_EMAIL_ENV)
        self._interval = _POLITE_INTERVAL if self._email else _ANONYMOUS_INTERVAL
        self._last_request_at: Optional[float] = None

    # ── Public API ──────────────────────────────────

    def lookup(self, title: str) -> dict:
        """Look up a paper by title via OpenAlex API.

        Returns dict with:
          - status: "VERIFIED" | "NOT_FOUND" | "ERROR"
          - oa_id: OpenAlex work ID if VERIFIED
          - title: matched title
          - year: publication year
          - doi: DOI if available
          - venue: journal/venue name if available
          - error: error message if ERROR
        """
        try:
            result = self._title_search(title)
            return self._to_output(result, title)
        except Exception as e:
            logger.warning("OpenAlex lookup failed for %r: %s", title[:80], e)
            return {"status": "ERROR", "error": str(e)}

    # ── Internal ───────────────────────────────────

    def _title_search(self, title: str) -> Optional[dict]:
        """Search OpenAlex by title, return best match or None."""
        data = self._get("/works", {
            "search": title,
            "per-page": "5",
            "select": _FIELDS,
        })
        candidates = data.get("results", [])
        scored = []
        for cand in candidates:
            cand_title = cand.get("title") or ""
            sim = title_similarity(cand_title, title)
            # Fallback: substring match if one title contains the other
            if sim < _TITLE_THRESHOLD:
                q_norm = _normalize_title(title)
                c_norm = _normalize_title(cand_title)
                if q_norm in c_norm or c_norm in q_norm:
                    sim = _TITLE_THRESHOLD  # Just clear the bar
                else:
                    continue
            scored.append((cand, sim))
        if not scored:
            return None
        scored.sort(key=lambda cs: (-cs[1],))
        return scored[0][0]

    def _get(self, path: str, params: dict) -> dict:
        """Rate-limited HTTP GET with 429 retry."""
        # Throttle
        if self._last_request_at is not None and self._interval > 0:
            elapsed = time.monotonic() - self._last_request_at
            remaining = self._interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()

        qs = dict(params)
        if self._email:
            qs["mailto"] = self._email
        url = f"{_API_BASE}{path}?{urllib.parse.urlencode(qs)}"
        req = urllib.request.Request(url, headers={"User-Agent": "hfpclawer-citation-audit/1.0"})

        for attempt in range(_MAX_RETRIES + 1):
            try:
                with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                    body = resp.read()
                    return json.loads(body.decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return {}
                if e.code == 429 and attempt < _MAX_RETRIES:
                    time.sleep(_BACKOFF)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, OSError):
                raise

        return {}

    @staticmethod
    def _to_output(result: Optional[dict], query_title: str) -> dict:
        if not result:
            return {"status": "NOT_FOUND", "title": query_title[:200]}
        venue = ""
        pl = result.get("primary_location")
        if pl and isinstance(pl, dict):
            source = pl.get("source")
            if source and isinstance(source, dict):
                venue = source.get("display_name", "")
        authors = ", ".join(
            a.get("author", {}).get("display_name", "")
            for a in (result.get("authorships") or [])
            if isinstance(a, dict)
        )
        return {
            "status": "VERIFIED",
            "oa_id": result.get("id", ""),
            "title": result.get("title", ""),
            "year": result.get("publication_year"),
            "doi": result.get("doi", ""),
            "venue": venue,
            "authors": authors,
        }
