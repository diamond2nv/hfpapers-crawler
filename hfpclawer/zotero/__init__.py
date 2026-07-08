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

    def search_by_doi(self, doi: str) -> Optional[dict]:
        """Search for an item by DOI using Zotero's quicksearch.

        Args:
            doi: DOI string (e.g., '10.1038/s41586-024-07123-5')

        Returns:
            First matching item dict, or None
        """
        items = self.items(q=doi, limit=5)
        for item in items:
            item_doi = item.get("data", {}).get("DOI", "")
            if item_doi and doi.lower() in item_doi.lower():
                return item
            # Also check extra field
            extra = item.get("data", {}).get("extra", "")
            if doi in extra:
                return item
        return None

    # ── Utility ──────────────────────────────────

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
