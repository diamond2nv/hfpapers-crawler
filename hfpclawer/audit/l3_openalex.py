#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l3_openalex.py — L3: OpenAlex API client for citation verification.

Migrated from hfpclawer.citation_audit_oa (CC BY-NC 4.0, Cheng-I Wu).
"""

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from hfpclawer.audit.similarity import normalize_title, title_similarity

logger = logging.getLogger("hfpclawer.audit.l3_openalex")

_API_BASE = "https://api.openalex.org"
_POLITE_EMAIL_ENV = "OPENALEX_POLITE_EMAIL"
_FIELDS = "id,title,authorships,publication_year,doi,primary_location"
_POLITE_INTERVAL = 0.1
_ANONYMOUS_INTERVAL = 1.0
_BACKOFF = 2.0
_MAX_RETRIES = 3
_TIMEOUT = 30
_TITLE_THRESHOLD = 0.70


class OAClient:
    """OpenAlex lookup client for citation verification."""

    def __init__(self, polite_email: Optional[str] = None):
        self._email = polite_email or os.environ.get(_POLITE_EMAIL_ENV)
        self._interval = _POLITE_INTERVAL if self._email else _ANONYMOUS_INTERVAL
        self._last_request_at: Optional[float] = None

    def lookup(self, title: str) -> dict:
        """Look up a paper by title via OpenAlex API."""
        try:
            result = self._title_search(title)
            return self._to_output(result, title)
        except Exception as e:
            logger.warning("OpenAlex lookup failed for %r: %s", title[:80], e)
            return {"status": "ERROR", "error": str(e)}

    def lookup_by_arxiv(self, arxiv_id: str) -> dict:
        """Look up a paper by arXiv ID via OpenAlex API."""
        data = self._get("/works", {"filter": f"arxiv_id:{arxiv_id}", "select": _FIELDS})
        results = data.get("results", [])
        if not results:
            return {"status": "NOT_FOUND", "arxiv_id": arxiv_id}
        r = results[0]
        return {
            "status": "VERIFIED",
            "oa_id": r.get("id"),
            "title": r.get("title"),
            "year": r.get("publication_year"),
            "doi": r.get("doi"),
            "arxiv_id": arxiv_id,
        }

    def _title_search(self, title: str) -> Optional[dict]:
        data = self._get("/works", {"search": title, "per-page": "5", "select": _FIELDS})
        candidates = data.get("results", [])
        scored = []
        for cand in candidates:
            cand_title = cand.get("title") or ""
            sim = title_similarity(cand_title, title)
            if sim < _TITLE_THRESHOLD:
                q_norm = normalize_title(title)
                c_norm = normalize_title(cand_title)
                if q_norm in c_norm or c_norm in q_norm:
                    sim = _TITLE_THRESHOLD
                else:
                    continue
            scored.append((cand, sim))
        if not scored:
            return None
        scored.sort(key=lambda cs: (-cs[1],))
        return scored[0][0]

    def _to_output(self, result: Optional[dict], query_title: str) -> dict:
        if not result:
            return {"status": "NOT_FOUND", "title": query_title[:200]}
        return {
            "status": "VERIFIED",
            "oa_id": result.get("id"),
            "title": result.get("title"),
            "year": result.get("publication_year"),
            "doi": result.get("doi"),
            "venue": (result.get("primary_location") or {}).get("source", {}).get("display_name"),
        }

    def _get(self, path: str, params: dict) -> dict:
        for attempt in range(_MAX_RETRIES):
            self._rate_limit()
            url = _API_BASE + path + "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={"User-Agent": "hfpclawer-audit/1.0"})
            if self._email:
                req.add_header("mailto", self._email)
            try:
                with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    logger.warning("OpenAlex 429, backing off %.1fs", _BACKOFF)
                    time.sleep(_BACKOFF)
                    continue
                raise
        return {}

    def _rate_limit(self):
        now = time.time()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            if elapsed < self._interval:
                time.sleep(self._interval - elapsed)
        self._last_request_at = time.time()
