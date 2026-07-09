#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zotero_client.py — hfpclawer Zotero integration via pyzotero local=True.

Provides high-level wrappers for Zotero READ operations over the local HTTP API
(localhost:23119). No API key required.

Usage:
    from hfpclawer.zotero.zotero_client import ZoteroClient
    
    zc = ZoteroClient()
    items = zc.top(limit=10)
    item = zc.get_item('ABC123')
    children = zc.get_children('ABC123')
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("hfpclawer.zotero")

# pyzotero is an optional dependency
try:
    from pyzotero import Zotero as _PyZotero
    HAS_PYZOTERO = True
except ImportError:
    _PyZotero = None
    HAS_PYZOTERO = False


class ZoteroConnectionError(Exception):
    """Raised when Zotero local API is unreachable."""


class ZoteroClient:
    """High-level wrapper for Zotero local API (read-only).

    Connects to Zotero Desktop's local HTTP API on port 23119.
    Requires: Zotero 7+ running with "Allow other applications to communicate"
    enabled in Preferences > Advanced.
    """

    def __init__(self, library_id: str = "0", timeout: float = 10.0):
        if not HAS_PYZOTERO:
            raise ImportError(
                "pyzotero is required. Install with: pip install pyzotero"
            )
        self._library_id = library_id
        self._timeout = timeout
        self._zot: Optional[_PyZotero] = None
        self._arxiv_lookup: Optional[dict[str, str]] = None

    def _connect(self) -> _PyZotero:
        """Lazy connection to Zotero local API."""
        if self._zot is not None:
            return self._zot
        try:
            self._zot = _PyZotero(
                library_id=self._library_id,
                library_type="user",
                local=True,
            )
            # Verify connection with a ping
            _ = self._zot.top(limit=1)
            logger.info("Connected to Zotero local API at localhost:23119")
            return self._zot
        except Exception as e:
            self._zot = None
            raise ZoteroConnectionError(
                f"Cannot connect to Zotero local API: {e}. "
                "Ensure Zotero is running and local API is enabled."
            ) from e

    # ── READ operations ──────────────────────────

    def top(
        self,
        limit: int = 50,
        start: int = 0,
        q: str = "",
        tag: str = "",
        item_type: str = "",
        **kwargs,
    ) -> list[dict]:
        """Get top-level items (no children: attachments, notes).

        Args:
            limit: Max items (default 50, local API has no hard limit)
            start: Offset for pagination
            q: Quick search query
            tag: Filter by tag (can be comma-separated for AND)
            item_type: Filter by item type (e.g., 'journalArticle')

        Returns:
            List of item dicts (Zotero API v3 format)
        """
        zot = self._connect()
        params: dict[str, Any] = {"limit": limit, "start": start}
        if q:
            params["q"] = q
        if tag:
            params["tag"] = tag.split(",")  # pyzotero handles AND for list
        if item_type:
            params["itemType"] = item_type
        params.update(kwargs)
        try:
            return list(zot.top(**params))
        except Exception as e:
            logger.warning("Zotero top() failed: %s", e)
            return []

    def items(
        self,
        limit: int = 50,
        start: int = 0,
        q: str = "",
        tag: str = "",
        item_type: str = "",
        **kwargs,
    ) -> list[dict]:
        """Get all items (including attachments, notes).

        Same parameters as top().
        """
        zot = self._connect()
        params: dict[str, Any] = {"limit": limit, "start": start}
        if q:
            params["q"] = q
        if tag:
            params["tag"] = tag.split(",")
        if item_type:
            params["itemType"] = item_type
        params.update(kwargs)
        try:
            return list(zot.items(**params))
        except Exception as e:
            logger.warning("Zotero items() failed: %s", e)
            return []

    def get_item(self, key: str) -> Optional[dict]:
        """Get a single item by its Zotero key.

        Args:
            key: Item key (e.g., 'ABC123' from list output)

        Returns:
            Item dict or None if not found
        """
        zot = self._connect()
        try:
            return zot.item(key)
        except Exception as e:
            logger.warning("Zotero item(%s) failed: %s", key, e)
            return None

    def get_children(self, key: str) -> list[dict]:
        """Get child items (attachments, notes) for a parent item.

        Args:
            key: Parent item key

        Returns:
            List of child item dicts
        """
        zot = self._connect()
        try:
            return list(zot.children(key))
        except Exception as e:
            logger.warning("Zotero children(%s) failed: %s", key, e)
            return []

    def collections(self) -> list[dict]:
        """Get all collections."""
        zot = self._connect()
        try:
            return list(zot.collections())
        except Exception as e:
            logger.warning("Zotero collections() failed: %s", e)
            return []

    def tags(self, collection_key: str = "") -> list[dict]:
        """Get all tags, optionally filtered by collection.

        Returns:
            List of tag dicts: [{"tag": "...", "meta": {"numItems": N}}]
        """
        zot = self._connect()
        try:
            if collection_key:
                return list(zot.collection_tags(collection_key))
            return list(zot.tags())
        except Exception as e:
            logger.warning("Zotero tags() failed: %s", e)
            return []

    def fulltext(self, key: str) -> Optional[str]:
        """Get full-text content for a PDF attachment.

        Args:
            key: Attachment item key (must be a PDF with extracted text)

        Returns:
            Full text string, or None if unavailable
        """
        zot = self._connect()
        try:
            result = zot.fulltext_item(key)
            if result and isinstance(result, dict):
                return result.get("content")
            return str(result) if result else None
        except Exception as e:
            logger.debug("Zotero fulltext(%s) failed: %s", key, e)
            return None

    def file_url(self, key: str) -> Optional[str]:
        """Get the local file URL for an attachment.

        Returns the file:// URL that Zotero redirects to.

        Args:
            key: Attachment item key

        Returns:
            file:// URL string, or None
        """
        zot = self._connect()
        try:
            # pyzotero's file() returns bytes; dump() saves to disk
            # For URL, we call the local API directly
            import urllib.request
            url = f"http://localhost:23119/api/users/{self._library_id}/items/{key}/file/view/url"
            req = urllib.request.urlopen(url, timeout=self._timeout)
            return req.read().decode().strip()
        except Exception as e:
            logger.debug("Zotero file_url(%s) failed: %s", key, e)
            return None

    # ── Dedup / Search by arXiv ID ──────────────

    def _fetch_all_items(self) -> list[dict]:
        """Fetch all items from Zotero via local HTTP API.

        Returns raw item dicts (no pagination needed for local API
        with a generous limit).
        """
        import urllib.request
        import json

        url = "http://localhost:23119/api/users/0/items?limit=5000"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            return []

    def _build_arxiv_lookup(self) -> dict[str, str]:
        """Build a dict of arxiv_id -> Zotero item key from all items.

        Scans the `extra` field and `url` field of every item.
        Returns a dict like {'2606.26294': '48NK3A83', ...}.

        Result is cached across calls within the same ZoteroClient instance.
        Call clear_lookup_cache() to force a refresh.
        """
        if self._arxiv_lookup is not None:
            return self._arxiv_lookup

        items = self._fetch_all_items()
        self._arxiv_lookup = {}
        for item in items:
            data = item.get("data", {})
            key = data.get("key", item.get("key", ""))
            extra = data.get("extra", "")
            url_field = data.get("url", "")

            # Check extra field for 'arXiv: XXXX.XXXXX'
            for line in extra.split("\n"):
                line = line.strip()
                for prefix in ("arXiv:", "arxiv:"):
                    if line.startswith(prefix):
                        aid = line[len(prefix):].strip()
                        if aid and "." in aid:
                            self._arxiv_lookup[aid] = key

            # Also check URL field for arxiv.org/abs/XXXX.XXXXX
            if "arxiv.org/abs/" in url_field:
                aid = url_field.split("arxiv.org/abs/")[-1]
                # Strip version suffix (v1, v2, etc.) and query params
                if "v" in aid and aid.split("v")[-1].isdigit():
                    aid = aid.rsplit("v", 1)[0]
                aid = aid.split("?")[0].split("#")[0]
                if aid and "." in aid:
                    self._arxiv_lookup.setdefault(aid, key)

        return self._arxiv_lookup

    def clear_lookup_cache(self) -> None:
        """Force a refresh of the arXiv lookup on the next dedup check."""
        self._arxiv_lookup = None

    def search_by_arxiv_id(
        self,
        arxiv_id: str,
        title: str = "",
        authors: list[str] | None = None,
        year: int | None = None,
    ) -> list[dict]:
        """Multi-level Zotero search by arXiv ID.

        Cascade (fast→slow):
          L0: In-memory arXiv lookup cache (instant)
          L1: Title keyword quick search → fuzzy match → verify  (if title known)
          L2: Full 5000-item scan (rebuilds cache)

        Args:
            arxiv_id: arXiv ID (e.g., "2606.26294")
            title: Paper title (optional — enables L1 fast path)
            authors: Author last names for verification (optional)
            year: Publication year for verification (optional)

        Returns:
            List with 0 or 1 matching item dicts.
        """
        # ── L0: in-memory cache ──
        key_from_cache = self._arxiv_lookup.get(arxiv_id) if self._arxiv_lookup else None
        if key_from_cache:
            item = self.get_item(key_from_cache)
            if item:
                return [item]

        # ── L1: title keyword search (fast, 1 API call) ──
        if title:
            try:
                match = self.find_by_title(title, authors=authors, year=year)
                if match:
                    m_key = (match.get("data", {}) or {}).get("key", "")
                    if m_key:
                        # Warm the cache
                        if self._arxiv_lookup is not None:
                            self._arxiv_lookup[arxiv_id] = m_key
                        return [match]
            except Exception:
                pass

        # ── L2: full scan (fetches all items once, caches result) ──
        if title:
            # With title, do one more targeted try via find_by_title with relaxed threshold
            try:
                match = self.find_by_title(title, min_similarity=0.40)
                if match:
                    m_key = (match.get("data", {}) or {}).get("key", "")
                    if m_key and self._arxiv_lookup is not None:
                        self._arxiv_lookup[arxiv_id] = m_key
                    return [match]
            except Exception:
                pass

        # Full scan fallback
        lookup = self._build_arxiv_lookup()
        target_key = lookup.get(arxiv_id)
        if not target_key:
            return []

        item = self.get_item(target_key)
        return [item] if item else []

    def is_arxiv_in_zotero(
        self,
        arxiv_id: str,
        title: str = "",
        authors: list[str] | None = None,
        year: int | None = None,
    ) -> Optional[str]:
        """Multi-level arXiv ID dedup check.

        Same cascade as ``search_by_arxiv_id`` but returns only the item key.

        Args:
            arxiv_id: arXiv ID (e.g., "2606.26294")
            title: Paper title (optional — enables fast keyword search path)
            authors: Author last names for verification (optional)
            year: Publication year for verification (optional)

        Returns:
            Zotero item key if found, None otherwise.
        """
        # L0: cache hit
        if self._arxiv_lookup:
            cached = self._arxiv_lookup.get(arxiv_id)
            if cached:
                return cached

        # L1: title keyword search (1 API call)
        if title:
            try:
                match = self.find_by_title(title, authors=authors, year=year)
                if match:
                    m_key = (match.get("data", {}) or {}).get("key", "")
                    if m_key:
                        if self._arxiv_lookup is not None:
                            self._arxiv_lookup[arxiv_id] = m_key
                        return m_key
            except Exception:
                pass

        # L2: full scan
        lookup = self._build_arxiv_lookup()
        return lookup.get(arxiv_id)

    def search_by_doi(
        self,
        doi: str,
        title: str = "",
    ) -> Optional[dict]:
        """Multi-level DOI search.

        Cascade:
          L0: Scan cached items if available (0 API calls)
          L1: Quick search with DOI string (1 API call, ~20ms)
          L2: Full 5000-item scan

        Args:
            doi: DOI string (e.g., '10.1038/s41467-025-63521-z')
            title: Paper title (optional — enables L1 with title+DOI combo)

        Returns:
            Matching item dict, or None.
        """
        doi_lower = doi.lower()

        # ── L0: scan cached items (no API call) ──
        if self._arxiv_lookup is not None and self._arxiv_lookup:
            # Cache exists — fetch items we already have
            items = self._fetch_all_items_from_cache()
            for item in items:
                data = item.get("data", {})
                item_doi = data.get("DOI", "")
                if item_doi and doi_lower in item_doi.lower():
                    return item
                extra = data.get("extra", "")
                if doi in extra:
                    return item

        # ── L1: quick search with DOI string ──
        # Zotero's FTS may index DOI in the extra field or url
        try:
            candidates = self.top(limit=10, q=doi_lower[:40])
            for item in candidates:
                data = item.get("data", {}) or {}
                item_doi = data.get("DOI", "")
                if item_doi and doi_lower in item_doi.lower():
                    return item
                extra = data.get("extra", "")
                if doi in extra:
                    return item
                # Also check: DOI often appears in URL
                url = data.get("url", "")
                if doi_lower in url.lower():
                    return item
        except Exception:
            pass

        # ── L1b: title + first author combo (if title given) ──
        if title:
            try:
                keywords = self._title_keywords(title, max_words=3)
                candidates = self.top(limit=10, q=f"{keywords} {doi_lower[:20]}")
                for item in candidates:
                    data = item.get("data", {}) or {}
                    item_doi = data.get("DOI", "")
                    if item_doi and doi_lower in item_doi.lower():
                        return item
            except Exception:
                pass

        # ── L2: full scan ──
        items = self._fetch_all_items()
        for item in items:
            data = item.get("data", {})
            item_doi = data.get("DOI", "")
            if item_doi and doi_lower in item_doi.lower():
                return item
            extra = data.get("extra", "")
            if doi in extra:
                return item
        return None

    def _fetch_all_items_from_cache(self) -> list[dict]:
        """Re-fetch all items using the cached lookup keys.

        Only fetches items whose keys are in the lookup, instead of
        doing a full 5000-item dump. Much faster when cache is warm.
        """
        if not self._arxiv_lookup:
            return []
        keys = list(self._arxiv_lookup.values())
        items = []
        import urllib.request
        import json
        for key in keys[:200]:  # limit to avoid flooding
            try:
                url = f"http://localhost:23119/api/users/0/items/{key}"
                with urllib.request.urlopen(url, timeout=10) as resp:
                    items.append(json.loads(resp.read().decode()))
            except Exception:
                pass
        return items

    TITLE_STOPWORDS = frozenset({
        "a", "an", "the", "of", "in", "on", "at", "to", "for", "with",
        "by", "and", "or", "is", "are", "was", "were", "be", "been",
        "has", "have", "had", "do", "does", "did", "will", "would",
        "can", "could", "may", "might", "shall", "should", "about",
        "into", "through", "during", "before", "after", "above",
        "below", "between", "out", "off", "over", "under", "again",
        "further", "then", "once", "here", "there", "when", "where",
        "why", "how", "all", "each", "every", "both", "few", "more",
        "most", "other", "some", "such", "no", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "because", "as",
        "until", "while", "of", "based", "using", "new", "novel",
        "method", "approach", "toward", "towards",
    })

    @staticmethod
    def _title_keywords(title: str, max_words: int = 5) -> str:
        """Extract meaningful keywords from a paper title for Zotero quick search.

        Strips stopwords and punctuation, returns space-separated keywords.
        Keeps the most distinctive 2-5 words.

        Examples:
            'A novel approach to neural PDE solvers' → 'neural PDE solvers'
            'On the complexity of LCLM training' → 'complexity LCLM training'
        """
        import re
        words = re.sub(r"[^\w\s-]", " ", title).split()
        # Filter stopwords, keep lowercase for matching
        filtered = [w for w in words if w.lower() not in ZoteroClient.TITLE_STOPWORDS and len(w) > 1]
        # Deduplicate while preserving order
        seen = set()
        unique = []
        for w in filtered:
            wl = w.lower()
            if wl not in seen:
                seen.add(wl)
                unique.append(w)
        # Keep original word order — Zotero's FTS uses proximity as ranking signal
        return " ".join(unique[:max_words])

    def find_by_title(
        self,
        title: str,
        authors: list[str] | None = None,
        year: int | None = None,
        min_similarity: float = 0.55,
    ) -> Optional[dict]:
        """Three-stage Zotero search: quick keyword → fuzzy title → verify.

        **Stage 1** — Quick search by title keywords (Zotero built-in FTS index).
                    Returns ≤20 candidates in milliseconds.

        **Stage 2** — Fuzzy title matching (SequenceMatcher ratio).
                    Accepts candidates above min_similarity (default 0.55).

        **Stage 3** — Author + year cross-verification on top match(es).

        Falls back to full-scan (``_build_arxiv_lookup``) if Stage 1-2 fail.

        Args:
            title: Paper title to search for.
            authors: Optional list of author last names for verification.
            year: Optional publication year for verification.
            min_similarity: Title similarity threshold [0, 1].

        Returns:
            Zotero item dict (with ``data`` sub-dict), or None.
        """
        from difflib import SequenceMatcher

        # ── Stage 1: keyword quick search ──
        keywords = self._title_keywords(title)
        if not keywords:
            return None
        try:
            candidates = self.top(limit=20, q=keywords)
        except Exception:
            candidates = []
        if not candidates:
            return None

        # ── Stage 2: fuzzy title matching ──
        scored: list[tuple[float, dict]] = []
        t_lower = title.lower()
        for item in candidates:
            item_title = (item.get("data", {}) or {}).get("title", "")
            if not item_title:
                continue
            sim = SequenceMatcher(None, t_lower, item_title.lower()).ratio()
            if sim >= min_similarity:
                scored.append((sim, item))

        if not scored:
            return None

        # Sort by similarity descending
        scored.sort(key=lambda x: -x[0])
        best_sim, best_match = scored[0]

        # ── Stage 3: verify by author + year ──
        if best_sim >= 0.85:
            # Very high similarity — return directly, skip verification
            return best_match

        if authors or year:
            # Try best match first
            verify_ok = self._verify_metadata(best_match, authors, year)
            if not verify_ok and len(scored) > 1:
                # Try next best candidates
                for _, candidate in scored[1:]:
                    if self._verify_metadata(candidate, authors, year):
                        return candidate

        return best_match

    @staticmethod
    def _verify_metadata(
        item: dict,
        authors: list[str] | None = None,
        year: int | None = None,
    ) -> bool:
        """Verify a Zotero item matches expected metadata.

        Checks author last names and publication year.
        Returns True if both checks pass or are not provided.
        """
        data = item.get("data", {}) or {}

        # Year check
        if year is not None:
            item_year = data.get("date", "")
            # Zotero date can be '2025', '2025-03', '2025-03-15'
            if item_year:
                try:
                    item_year_int = int(str(item_year)[:4])
                    if abs(item_year_int - year) > 2:
                        return False
                except (ValueError, TypeError):
                    pass  # Can't parse, skip check

        # Author check
        if authors:
            creators = data.get("creators", [])
            item_last_names = {
                c.get("lastName", "").lower()
                for c in creators
                if c.get("lastName")
            }
            target_last_names = {
                a.strip().lower().split()[-1]  # take last word as surname
                for a in authors if a.strip()
            }
            # Require at least one author last name match
            if target_last_names and not (item_last_names & target_last_names):
                return False

        return True

    def check_connection(self) -> bool:
        """Verify Zotero local API is accessible.

        Returns:
            True if connected, False otherwise
        """
        try:
            self._connect()
            return True
        except ZoteroConnectionError:
            return False

    @property
    def is_connected(self) -> bool:
        """Check if connection is established (lazy)."""
        return self._zot is not None

    @property
    def library_summary(self) -> dict:
        """Get a quick summary of the Zotero library."""
        zot = self._connect()
        try:
            items = zot.top(limit=1)
            tags = zot.tags()
            total_header = items  # We just need the headers
            return {
                "total_items": None,  # local API doesn't return total-count easily
                "total_tags": len(tags),
                "connected": True,
            }
        except Exception:
            return {"connected": False}
