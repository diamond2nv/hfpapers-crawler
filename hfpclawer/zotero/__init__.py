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
import os
import urllib.request
from typing import Any, Optional

logger = logging.getLogger("hfpclawer.zotero")

# ── Shared Zotero URL resolution ──────────────────────
# All modules (__init__, connector, annotations, cli) use get_zotero_url()
# so a single ZOTERO_API_URL env var sets the remote Zotero instance for all.

_ZOTERO_BASE_URL_CACHE: str | None = None
_DOTENV_LOADED = False


def _ensure_dotenv() -> None:
    """Load .env file once via python-dotenv (if available).

    Search order (first match wins):
      1. CWD → parent directories (load_dotenv() default behavior)
      2. ~/.config/hfpclawer/.env (XDG standard for CLI tools)
      3. ~/.hfpclawer/.env (legacy fallback)
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    try:
        from dotenv import load_dotenv
        from pathlib import Path

        # 1. CWD upward (covers dev repo, project dirs)
        load_dotenv()
        # 2. XDG user config dir
        load_dotenv(Path.home() / ".config" / "hfpclawer" / ".env", override=False)
        # 3. Legacy fallback
        load_dotenv(Path.home() / ".hfpclawer" / ".env", override=False)
    except Exception:
        pass  # dotenv not installed or .env missing — just use os.environ


def _get_env(key: str, default: str = "") -> str:
    """Read env var, with .env support via python-dotenv.

    Calls load_dotenv() once per process so .env values are picked up
    without needing a manual export.
    """
    _ensure_dotenv()
    return os.environ.get(key, default).strip()


def get_zotero_url() -> str:
    """Get the Zotero base URL, resolved once per process.

    Resolution order:
      1. ZOTERO_API_URL environment variable (e.g. http://192.168.0.103:23120)
      2. Default: http://localhost:23119

    ZOTERO_API_URL can be set via:
      - Environment variable (export)
      - .env file (python-dotenv, loaded automatically)

    Returns the base URL WITHOUT trailing slash (e.g. 'http://localhost:23119').
    """
    global _ZOTERO_BASE_URL_CACHE
    if _ZOTERO_BASE_URL_CACHE is not None:
        return _ZOTERO_BASE_URL_CACHE
    _ensure_dotenv()
    _ZOTERO_BASE_URL_CACHE = (
        os.environ.get("ZOTERO_API_URL") or "http://localhost:23119"
    ).rstrip("/")
    return _ZOTERO_BASE_URL_CACHE


def is_zotero_remote() -> bool:
    """Check if the configured Zotero URL points to a remote host.

    When True, all HTTP requests should spoof the Host header as
    ``localhost:23119`` so Zotero's ``httpd.js`` Host check passes.
    """
    netloc = get_zotero_url().split("://", 1)[-1].split("/")[0].split(":")[0]
    return netloc not in ("localhost", "127.0.0.1", "::1")


def _zotero_api_path(path: str) -> str:
    """Build an absolute URL to a Zotero API endpoint.

    Args:
        path: API path with leading slash (e.g. '/items/ABC123')
              or absolute URL (passed through unchanged).
    """
    if path.startswith("http://") or path.startswith("https://"):
        return path
    base = get_zotero_url()
    return f"{base}/api/users/0{path}"


def _zotero_request(
    url: str,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> urllib.request.Request:
    """Build a urllib Request with automatic Host spoofing for remote Zotero.

    Args:
        url: Absolute URL (may be built with _zotero_api_path()).
        method: HTTP method (default GET).
        body: Optional request body bytes.
        headers: Additional headers. Host spoofing is auto-injected when
                 the configured Zotero URL is remote.
        timeout: Request timeout in seconds.

    Returns:
        Prepared urllib.request.Request.

    Raises:
        urllib.error.URLError / HTTPError from urlopen().
    """
    req_headers = dict(headers) if headers else {}
    req_headers.setdefault("Content-Type", "application/json")
    req_headers.setdefault("User-Agent", "pyzotero/1.13.2")
    req_headers.setdefault("Zotero-API-Version", "3")
    if is_zotero_remote():
        req_headers["Host"] = "localhost:23119"
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


# Add settable cache for testing
def _reset_zotero_url_cache() -> None:
    """Reset the cached Zotero URL (for testing)."""
    global _ZOTERO_BASE_URL_CACHE
    _ZOTERO_BASE_URL_CACHE = None

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
        """Lazy connection to Zotero API (local or remote).

        Auto-detection sequence:
          1. ZOTERO_API_URL env var → remote Zotero (with Host spoofing)
          2. WSL gateway detection → Windows host Zotero via NAT
          3. Default → localhost:23119
        """
        if self._zot is not None:
            return self._zot
        try:
            self._zot = _PyZotero(
                library_id=self._library_id,
                library_type="user",
                local=True,
            )
            base_url = get_zotero_url()
            is_remote = is_zotero_remote()
            wsl_gateway = self._detect_wsl_gateway()

            # ── Case A: env var ZOTERO_API_URL set — use as-is ──
            if is_remote:
                self._zot.endpoint = f"{base_url}/api"
                self._zot.client = self._make_httpx_client(base_url)
                logger.info(
                    "Remote Zotero via %s (Host spoofed as localhost:23119)",
                    base_url,
                )
            # ── Case B: inside WSL → Windows gateway ──
            elif wsl_gateway:
                gw_url = f"http://{wsl_gateway}:23119"
                self._zot.endpoint = f"{gw_url}/api"
                self._zot.client = self._make_httpx_client(gw_url)
                logger.info(
                    "WSL→Windows Zotero via %s:23119 (Host spoofed as localhost)",
                    wsl_gateway,
                )
            # ── Case C: localhost (default pyzotero local=True) ──
            else:
                logger.info("Zotero at localhost:23119")

            # Verify connection with a ping
            _ = self._zot.top(limit=1)
            logger.info("Connected to Zotero API at %s", base_url)
            return self._zot
        except Exception as e:
            self._zot = None
            raise ZoteroConnectionError(
                f"Cannot connect to Zotero at {get_zotero_url()}: {e}. "
                "Ensure Zotero is running and local API is enabled."
            ) from e

    def _make_httpx_client(self, base_url: str):
        """Create an httpx.Client with Host spoofing for remote Zotero."""
        import httpx
        return httpx.Client(
            headers={
                "User-Agent": "pyzotero/1.13.2",
                "Zotero-API-Version": "3",
                "Host": "localhost:23119",
                "Content-Type": "application/json",
            },
            follow_redirects=True,
            timeout=httpx.Timeout(self._timeout),
        )

    @staticmethod
    def _detect_wsl_gateway() -> str | None:
        """Detect if running inside WSL and return Windows gateway IP."""
        try:
            with open("/proc/version") as f:
                if "microsoft" not in f.read().lower():
                    return None  # Not WSL
            import subprocess
            result = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True, text=True, timeout=3,
            )
            parts = result.stdout.strip().split()
            if len(parts) >= 3:
                return parts[2]  # Gateway IP (e.g. 172.26.160.1)
        except Exception:
            pass
        return None

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
            url = _zotero_api_path(f"/items/{key}/file/view/url")
            with _zotero_request(url, timeout=self._timeout) as resp:
                return resp.read().decode().strip()
        except Exception as e:
            logger.debug("Zotero file_url(%s) failed: %s", key, e)
            return None

    # ── Dedup / Search by arXiv ID ──────────────

    def _fetch_all_items(self) -> list[dict]:
        """Fetch all items from Zotero via local HTTP API.

        Returns raw item dicts (no pagination needed for local API
        with a generous limit).
        """
        url = _zotero_api_path("/items?limit=5000")
        try:
            with _zotero_request(url, timeout=30) as resp:
                import json
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
        import json
        for key in keys[:200]:  # limit to avoid flooding
            try:
                url = _zotero_api_path(f"/items/{key}")
                with _zotero_request(url, timeout=10) as resp:
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
    def _title_keywords(title: str, max_words: int = 6) -> str:
        """Extract meaningful keywords from a paper title for Zotero quick search.

        Uses spaCy-enhanced NLP when available (lemmatization + noun chunks).
        Falls back to enhanced regex-based extraction otherwise.

        Examples:
            'A novel approach to neural PDE solvers' → 'neural pde solver' (spaCy)
            'On the complexity of LCLM training' → 'complexity LCLM training' (fallback)
        """
        # Try spaCy-enhanced extraction first
        try:
            from hfpapers.nlp.keywords import title_keywords as _nlp_keywords
            result = _nlp_keywords(title, max_words=max_words)
            if result:
                return result
        except Exception:
            pass

        # Fallback: enhanced regex-based extraction
        import re
        words = re.sub(r"[^\w\s-]", " ", title).split()
        filtered = [w for w in words if w.lower() not in ZoteroClient.TITLE_STOPWORDS and len(w) > 1]
        seen = set()
        unique = []
        for w in filtered:
            wl = w.lower()
            if wl not in seen:
                seen.add(wl)
                unique.append(w)
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

        # ── Stage 2: fuzzy title matching with optional vector rerank ──
        scored: list[tuple[float, dict]] = []
        low_scored: list[tuple[float, dict]] = []  # Borderline: may be boosted by vectors
        t_lower = title.lower()
        for item in candidates:
            item_title = (item.get("data", {}) or {}).get("title", "")
            if not item_title:
                continue
            sim = SequenceMatcher(None, t_lower, item_title.lower()).ratio()
            if sim >= min_similarity:
                scored.append((sim, item))
            elif sim >= 0.30:
                # Borderline — may be boosted by spaCy vectors
                low_scored.append((sim, item))

        # ── Stage 2b: semantic reranking for borderline candidates ──
        if low_scored and not scored:
            # Only run rerank if no high-confidence match found yet
            try:
                from hfpapers.nlp.search import semantic_rerank
                for sim, item in low_scored:
                    item_title = (item.get("data", {}) or {}).get("title", "")
                    boosted = semantic_rerank(title, item_title, sim)
                    if boosted >= min_similarity:
                        scored.append((boosted, item))
            except Exception:
                pass  # Graceful degradation

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

    def update_item_extra(
        self,
        key: str,
        extra_fields: dict[str, str],
    ) -> bool:
        """Append structured metadata to a Zotero item's ``extra`` field.

        Uses the Zotero local API (``PUT /api/users/0/items/{key}``).
        Does NOT require API key when ``local=True``.

        The extra field is free-text but commonly stores structured key:value
        pairs. This method appends ``innovation_key`` lines for each entry.

        Args:
            key: Zotero item key (e.g. 'ABC123').
            extra_fields: Dict of label→value pairs to write, e.g.
                ``{"innovation_method": "Fourier Neural Operator",
                   "innovation_field": "PDE surrogates"}``.

        Returns:
            True on success, False on failure.
        """
        zot = self._connect()
        try:
            item = zot.item(key)
        except Exception as e:
            logger.warning("Cannot fetch item %s for extra update: %s", key, e)
            return False

        if not item or not item.get("data"):
            return False

        data = item["data"]
        current_extra = data.get("extra", "") or ""

        # Build new extra lines, replace any existing innovation_ lines
        new_lines: list[str] = []
        innovation_keys_seen = set(extra_fields.keys())
        for line in current_extra.split("\n"):
            line_stripped = line.strip()
            # Remove old innovation lines that we're about to replace
            if any(line_stripped.startswith(k + ":") for k in innovation_keys_seen):
                continue
            if line_stripped:
                new_lines.append(line)

        # Append new innovation fields
        innovation_lines = [
            f"{label}: {value}"
            for label, value in extra_fields.items()
            if value
        ]
        if new_lines and new_lines[-1] != "":
            new_lines.append("")  # spacer
        new_lines.extend(innovation_lines)

        data["extra"] = "\n".join(new_lines).strip()

        # PUT back via local API
        try:
            import json
            body = json.dumps(item).encode("utf-8")
            url = _zotero_api_path(f"/items/{key}")
            with _zotero_request(url, method="PUT", body=body, timeout=15) as resp:
                if resp.status in (200, 204):
                    logger.info("Extra field updated for %s: %s", key, extra_fields)
                    return True
                logger.warning("PUT item %s returned %s", key, resp.status)
                return False
        except Exception as e:
            logger.warning("Failed to update extra for %s: %s", key, e)
            return False

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
