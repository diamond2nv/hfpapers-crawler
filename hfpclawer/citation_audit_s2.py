#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
citation_audit_s2.py — Semantic Scholar API client for citation verification.

Architecture reference: academic-research-skills/scripts/semantic_scholar_client.py
by Cheng-I Wu (CC BY-NC 4.0).

This is a simplified version — no outage latch, no DOI_MISMATCH Protocol,
no contamination-signals integration. Just: lookup_by_doi + lookup_by_title
with rate-limit pacing and 429 backoff.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from hfpclawer._text_similarity import title_similarity

logger = logging.getLogger("hfpclawer.citation_audit_s2")

_API_BASE = "https://api.semanticscholar.org/graph/v1"
_API_KEY_ENV = "S2_API_KEY"
_FIELDS = "title,authors,year,externalIds,venue,publicationDate"

# Rate limits
_UNAUTH_INTERVAL = 1.0  # 1 req/s unauthenticated
_AUTH_INTERVAL = 0.1    # 10 req/s with API key
_BACKOFF = 2.0           # Seconds to sleep on 429
_MAX_RETRIES = 3
_TIMEOUT = 30

# Threshold (from ARS protocol, locked)
_TITLE_THRESHOLD = 0.70


class S2Client:
    """Semantic Scholar lookup client for citation verification.

    Simplified from ARS: no outage latch, no Protocol contracts.
    Just DOI-first, title-fallback with pacing.

    Usage:
        client = S2Client()
        result = client.lookup("Attention Is All You Need")
        # -> {"status": "VERIFIED"|"NOT_FOUND"|"ERROR", "paper_id": ...}
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get(_API_KEY_ENV)
        self._interval = _AUTH_INTERVAL if self._api_key else _UNAUTH_INTERVAL
        self._last_request_at: Optional[float] = None

    # ── Public API ──────────────────────────────────

    def lookup(self, title: str) -> dict:
        """Look up a paper by title via S2 API.

        Returns dict with:
          - status: "VERIFIED" | "NOT_FOUND" | "ERROR"
          - paper_id: S2 paper ID (str) if VERIFIED
          - title: matched title if VERIFIED
          - year: matched year if available
          - venue: matched venue if available
          - error: error message if ERROR
        """
        try:
            result = self._lookup_by_title(title)
            return self._to_output(result, title)
        except Exception as e:
            logger.warning("S2 lookup failed for %r: %s", title[:80], e)
            return {"status": "ERROR", "error": str(e)}

    # ── Internal lookup logic ──────────────────────

    def _lookup_by_title(self, title: str) -> dict:
        """Search S2 by title, return best match dict or empty."""
        path = (
            f"/paper/search?query={urllib.parse.quote(title)}"
            f"&limit=5&fields={_FIELDS}"
        )
        data = self._request(path)
        candidates = data.get("data") or []

        best = None  # (score, candidate)
        for cand in candidates:
            cand_title = cand.get("title") or ""
            sim = title_similarity(title, cand_title)
            if sim < _TITLE_THRESHOLD:
                # Fallback: substring match
                from hfpclawer._text_similarity import _normalize_title
                q_norm = _normalize_title(title)
                c_norm = _normalize_title(cand_title)
                if q_norm in c_norm or c_norm in q_norm:
                    sim = _TITLE_THRESHOLD
                else:
                    continue
            if best is None or sim > best[0]:
                best = (sim, cand)

        if best is None:
            return {}
        return best[1]

    def _request(self, path: str) -> dict:
        """Rate-limited HTTP GET with 429 retry."""
        # Rate limit pacing
        if self._last_request_at is not None and self._interval > 0:
            elapsed = time.monotonic() - self._last_request_at
            remaining = self._interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()

        url = f"{_API_BASE}{path}"
        headers = {"User-Agent": "hfpclawer-citation-audit/1.0"}
        if self._api_key:
            headers["x-api-key"] = self._api_key
        req = urllib.request.Request(url, headers=headers)

        for attempt in range(_MAX_RETRIES + 1):
            try:
                with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return {}
                if e.code == 429 and attempt < _MAX_RETRIES:
                    time.sleep(_BACKOFF)
                    continue
                raise
            except urllib.error.URLError:
                raise
            except (OSError, TimeoutError):
                raise

        return {}

    # ── Output formatting ──────────────────────────

    @staticmethod
    def _to_output(result: dict, query_title: str) -> dict:
        if not result or not result.get("paperId"):
            return {"status": "NOT_FOUND", "title": query_title[:200]}
        return {
            "status": "VERIFIED",
            "paper_id": result.get("paperId"),
            "title": result.get("title", ""),
            "year": result.get("year"),
            "venue": result.get("venue"),
            "authors": ", ".join(
                a.get("name", "") for a in (result.get("authors") or [])
            ) if result.get("authors") else "",
        }
