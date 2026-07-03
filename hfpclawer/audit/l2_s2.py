#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_s2.py — L2: Semantic Scholar API client for citation verification.

Migrated from hfpclawer.citation_audit_s2 (CC BY-NC 4.0, Cheng-I Wu).
"""

import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from hfpclawer.audit.similarity import normalize_title, title_similarity

logger = logging.getLogger("hfpclawer.audit.l2_s2")

_API_BASE = "https://api.semanticscholar.org/graph/v1"
_API_KEY_ENV = "S2_API_KEY"
_FIELDS = "title,authors,year,externalIds,venue,publicationDate"

_UNAUTH_INTERVAL = 1.0
_AUTH_INTERVAL = 0.1
_BACKOFF = 2.0
_MAX_RETRIES = 3
_TIMEOUT = 30
_TITLE_THRESHOLD = 0.70


class S2Client:
    """Semantic Scholar lookup client for citation verification."""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get(_API_KEY_ENV)
        self._interval = _AUTH_INTERVAL if self._api_key else _UNAUTH_INTERVAL
        self._last_request_at: Optional[float] = None

    def lookup(self, title: str) -> dict:
        """Look up a paper by title via S2 API.

        Returns dict with status: VERIFIED | NOT_FOUND | ERROR.
        """
        try:
            result = self._lookup_by_title(title)
            return self._to_output(result, title)
        except Exception as e:
            logger.warning("S2 lookup failed for %r: %s", title[:80], e)
            return {"status": "ERROR", "error": str(e)}

    def lookup_by_arxiv(self, arxiv_id: str) -> dict:
        """Look up a paper by arXiv ID via S2 API."""
        path = f"/paper/arXiv:{arxiv_id}?fields={_FIELDS}"
        try:
            data = self._request(path)
            if not data or "paperId" not in data:
                return {"status": "NOT_FOUND", "arxiv_id": arxiv_id}
            return {
                "status": "VERIFIED",
                "paper_id": data.get("paperId"),
                "title": data.get("title"),
                "year": data.get("year"),
                "venue": data.get("venue"),
                "arxiv_id": arxiv_id,
            }
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"status": "NOT_FOUND", "arxiv_id": arxiv_id}
            return {"status": "ERROR", "error": str(e)}

    def _lookup_by_title(self, title: str) -> dict:
        path = (f"/paper/search?query={urllib.parse.quote(title)}"
                f"&limit=5&fields={_FIELDS}")
        data = self._request(path)
        candidates = data.get("data") or []
        best = None
        for cand in candidates:
            cand_title = cand.get("title") or ""
            sim = title_similarity(title, cand_title)
            if sim < _TITLE_THRESHOLD:
                q_norm = normalize_title(title)
                c_norm = normalize_title(cand_title)
                if q_norm in c_norm or c_norm in q_norm:
                    sim = _TITLE_THRESHOLD
                else:
                    continue
            if best is None or sim > best[0]:
                best = (sim, cand)
        return best[1] if best else {}

    def _to_output(self, result: dict, query_title: str) -> dict:
        if not result or not result.get("title"):
            return {"status": "NOT_FOUND", "title": query_title[:200]}
        return {
            "status": "VERIFIED",
            "paper_id": result.get("paperId"),
            "title": result.get("title"),
            "year": result.get("year"),
            "venue": result.get("venue"),
            "external_ids": result.get("externalIds"),
        }

    def _request(self, path: str) -> dict:
        for attempt in range(_MAX_RETRIES):
            self._rate_limit()
            url = _API_BASE + path
            req = urllib.request.Request(url, headers={"User-Agent": "hfpclawer-audit/1.0"})
            if self._api_key:
                req.add_header("x-api-key", self._api_key)
            try:
                with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                return data
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    logger.warning("S2 429, backing off %.1fs", _BACKOFF)
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


import json  # noqa: E402
