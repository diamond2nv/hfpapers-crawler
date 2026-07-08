#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""connector.py — hfpclawer → Zotero WRITE via Connector protocol.

Simulates the Zotero Connector (browser extension) by POSTing item metadata
directly to Zotero Desktop's /connector/saveItems endpoint.

No API key required. No internet required. No browser extension needed.
PDF attachments are IGNORED by design (Zotero handles them via sync).

Protocol derived from Zotero source code:
  chrome/content/zotero/xpcom/server/server_connector.js
  chrome/content/zotero/xpcom/server/saveSession.js

Usage:
    from hfpclawer.zotero.connector import ZoteroConnector

    zc = ZoteroConnector()
    result = zc.save_items([{
        "itemType": "journalArticle",
        "title": "Paper Title",
        "creators": [...],
        "tags": [{"tag": "hfpclawer", "type": 1}],
        "DOI": "10.xxx/xxxx",
        "url": "https://arxiv.org/abs/xxxx.yyyyy",
    }], uri="https://arxiv.org/abs/xxxx.yyyyy")
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

import urllib.request
import urllib.error

logger = logging.getLogger("hfpclawer.zotero.connector")

# Default Zotero local connector endpoint
CONNECTOR_URL = "http://localhost:23119/connector"

# Connector API version (matching Zotero source)
CONNECTOR_API_VERSION = 3


class ConnectorError(Exception):
    """Raised when the Connector protocol request fails."""


class ZoteroConnector:
    """Low-level Zotero Connector protocol client.

    Sends item data to Zotero Desktop as if sent by the browser extension.
    All operations are local — no API key, no internet.
    """

    def __init__(self, connector_url: str = CONNECTOR_URL, timeout: float = 15.0):
        self._url = connector_url.rstrip("/")
        self._timeout = timeout

    def save_items(
        self,
        items: list[dict[str, Any]],
        uri: str = "",
        session_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Save one or more items to Zotero via /connector/saveItems.

        This is the primary write method. It mimics exactly what the browser
        extension does when a user clicks "Save to Zotero".

        Args:
            items: List of item dicts in Zotero API v3 format.
                   Each item must have at least "itemType" and "title".
                   Optional fields: creators, tags, DOI, url, date,
                   publicationTitle, abstractNote, extra, notes, etc.
            uri: Source URI (the webpage URL where the item was found).
                 Used as the reference URI for the save session.
            session_id: Optional session ID. Auto-generated if not provided.

        Returns:
            dict with:
              - "status": 201 on success
              - "session_id": the session ID used
              - "error": error message if failed

        Raises:
            ConnectorError: If the connector endpoint is unreachable.
        """
        sid = session_id or _make_session_id()
        payload = {
            "sessionID": sid,
            "items": items,
        }
        if uri:
            payload["uri"] = uri
        else:
            # Use first item's URL as fallback
            first_url = items[0].get("url", "") if items else ""
            payload["uri"] = first_url or "https://arxiv.org/abs/unknown"

        return self._request("saveItems", payload, sid)

    def save_single_file(
        self,
        session_id: str,
        url: str,
        content: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Save a web snapshot (HTML content) to an existing save session.

        Used for saving full webpage snapshots via the SingleFile format.
        For hfpclawer use, this would be for HTML snapshots of paper pages.

        Args:
            session_id: Session ID from a previous save_items() call.
            url: The URL of the saved page.
            content: HTML content (SingleFile format).
            metadata: Optional metadata dict.

        Returns:
            dict with status and session_id.
        """
        payload = {
            "sessionID": session_id,
            "url": url,
            "content": content,
        }
        if metadata:
            payload.update(metadata)
        return self._request("saveSingleFile", payload, session_id)

    def save_attachment(
        self,
        session_id: str,
        parent_item_key: str,
        pdf_path: str,
        title: str = "",
        url: str = "",
    ) -> dict[str, Any]:
        """Attach a PDF file to an existing Zotero item via /connector/saveAttachment.

        POSTs raw PDF bytes with X-Metadata header describing the parent item.
        Call this AFTER a successful save_items() — the parent item must already
        exist in Zotero.

        Args:
            session_id: Session ID from the save_items() call.
            parent_item_key: Zotero item key of the parent (from getRecognizedItem).
            pdf_path: Absolute path to the PDF file on disk.
            title: Optional attachment title (defaults to PDF filename).
            url: Optional source URL for the attachment.

        Returns:
            dict with:
              - "status": 201 on success
              - "session_id": the session ID used
              - "error": error message if failed

        Raises:
            ConnectorError: If Zotero is unreachable.
            FileNotFoundError: If pdf_path doesn't exist.
        """
        import os
        import json as _json

        if not os.path.isfile(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        # Build X-Metadata header
        metadata = {
            "sessionID": session_id,
            "parentItemID": parent_item_key,
            "title": title or os.path.basename(pdf_path),
        }
        if url:
            metadata["url"] = url

        # Read PDF bytes
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        target_url = f"{self._url}/saveAttachment"
        headers = {
            "Content-Type": "application/octet-stream",
            "X-Metadata": _json.dumps(metadata, ensure_ascii=False),
        }

        req = urllib.request.Request(
            target_url, data=pdf_bytes, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                status = resp.status
                resp_body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            status = e.code
            resp_body = e.read().decode("utf-8") if e.fp else ""
        except urllib.error.URLError as e:
            raise ConnectorError(
                f"Cannot reach Zotero at {target_url}: {e.reason}. "
                "Ensure Zotero is running."
            ) from e

        result: dict[str, Any] = {
            "status": status,
            "session_id": session_id,
        }
        if resp_body:
            try:
                result["response"] = _json.loads(resp_body)
            except _json.JSONDecodeError:
                result["response_text"] = resp_body

        if 200 <= status < 300:
            logger.info(
                "saveAttachment session=%s parent=%s status=%d size=%d",
                session_id[:8], parent_item_key, status, len(pdf_bytes),
            )
        else:
            error_msg = result.get("response", {}).get("error", resp_body[:200])
            logger.warning(
                "saveAttachment session=%s failed: %d %s",
                session_id[:8], status, error_msg,
            )
            result["error"] = str(error_msg)

        return result

    def get_recognized_item(self, session_id: str) -> Optional[dict]:
        """Check the top-level item created in a save session.

        Use this after save_items() to get the Zotero item key.

        Args:
            session_id: Session ID from a previous save_items() call.

        Returns:
            dict with "title" and "itemType", or None if no item recognized yet.
        """
        payload = {"sessionID": session_id}
        try:
            result = self._request("getRecognizedItem", payload, session_id)
            return result if result else None
        except ConnectorError:
            return None

    # ── Internal helpers ────────────────────────

    def _request(
        self,
        method: str,
        payload: dict[str, Any],
        session_id: str,
    ) -> dict[str, Any]:
        """Send a POST request to a connector endpoint.

        Args:
            method: Connector method name (e.g., "saveItems", "getRecognizedItem")
            payload: JSON-serializable dict to send.
            session_id: Session ID for logging.

        Returns:
            Parsed response dict.

        Raises:
            ConnectorError: On HTTP or connection errors.
        """
        url = f"{self._url}/{method}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Zotero-Connector-API-Version": str(CONNECTOR_API_VERSION),
        }

        logger.debug(
            "POST %s session=%s items=%d",
            url, session_id[:8], len(payload.get("items", [])),
        )

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                status = resp.status
                resp_body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            status = e.code
            resp_body = e.read().decode("utf-8") if e.fp else ""
        except urllib.error.URLError as e:
            raise ConnectorError(
                f"Cannot reach Zotero at {url}: {e.reason}. "
                "Ensure Zotero is running."
            ) from e

        result: dict[str, Any] = {
            "status": status,
            "session_id": session_id,
        }

        if resp_body:
            try:
                result["response"] = json.loads(resp_body)
            except json.JSONDecodeError:
                result["response_text"] = resp_body

        if 200 <= status < 300:
            logger.info("Connector %s session=%s status=%d", method, session_id[:8], status)
        else:
            error_msg = result.get("response", {}).get("error", resp_body[:200])
            logger.warning(
                "Connector %s session=%s failed: %d %s",
                method, session_id[:8], status, error_msg,
            )
            result["error"] = str(error_msg)

        return result

    # ── High-level helpers ──────────────────────

    def push_paper_from_store(
        self,
        arxiv_id: str,
        paper_store_lookup: Any = None,
        session_id: Optional[str] = None,
        dedup: bool = True,
    ) -> dict[str, Any]:
        """Push a paper from paper_store to Zotero.

        Looks up the paper by arxiv_id, constructs a Zotero-compatible item,
        and sends it via the Connector protocol.

        Args:
            arxiv_id: arXiv ID (e.g., "2501.01934")
            paper_store_lookup: Callable(arxiv_id) -> dict or None.
                                If None, uses hfpapers.paper_store.ensure_paper.
            session_id: Optional session ID override.
            dedup: If True (default), skip if paper already exists in Zotero.

        Returns:
            Result dict from save_items().
        """
        # Dedup check — Zotero READ only, safe during sync
        if dedup:
            try:
                from hfpclawer.zotero import ZoteroClient
                zc = ZoteroClient()
                existing_key = zc.is_arxiv_in_zotero(arxiv_id)
                if existing_key:
                    return {
                        "status": 304,
                        "error": f"Already in Zotero (key={existing_key})",
                        "skipped": True,
                    }
            except Exception as e:
                logger.debug("Dedup check failed (proceeding anyway): %s", e)

        # Resolve paper data
        if paper_store_lookup is not None:
            paper = paper_store_lookup(arxiv_id)
        else:
            paper = self._lookup_paper_store(arxiv_id)

        if not paper:
            return {"status": 404, "error": f"Paper '{arxiv_id}' not found in paper_store"}

        # Build Zotero item
        item = paper_to_zotero_item(paper)
        uri = paper.get("url", "") or f"https://arxiv.org/abs/{arxiv_id}"

        return self.save_items([item], uri=uri, session_id=session_id)

    @staticmethod
    def _lookup_paper_store(arxiv_id: str) -> Optional[dict]:
        """Look up a paper in hfpclawer's paper_store by arXiv ID."""
        try:
            from hfpapers.paper_store import get_store

            store = get_store()
            paper = store.get_paper_by_identifier("arxiv", arxiv_id)
            if not paper:
                return None

            # paper is a PaperRecord dataclass
            ids = store.get_identifiers(paper.sf_id) or []
            doi = next(
                (i.id_value for i in ids if i.id_type == "doi"), ""
            )

            return {
                "title": paper.title or "",
                "abstract": paper.abstract or "",
                "doi": doi,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "venue": paper.venue or "",
                "source": paper.source or "",
                "relevance": paper.relevance or 0,
                "sf_id": paper.sf_id,
                "arxiv_id": arxiv_id,
            }
        except Exception as e:
            logger.warning("paper_store lookup failed: %s", e)
            return None


def paper_to_zotero_item(paper: dict[str, Any]) -> dict[str, Any]:
    """Convert a paper dict to Zotero API v3 item format.

    Args:
        paper: Dict with keys: title, abstract, doi, url, venue, arxiv_id, etc.

    Returns:
        Zotero-compatible item dict.

    Notes on tags:
        The Zotero Connector protocol forces forceTagType=1 for all tags.
        If the user has "Automatic Tags" DISABLED in Zotero > Preferences > General,
        tags will be silently dropped by Zotero's ItemSaver._cleanTags().
        The `extra` field always survives — use it for hfpclawer tracking.
    """
    title = paper.get("title", "Untitled")[:500]
    abstract = (paper.get("abstract") or "")[:2000]
    doi = paper.get("doi", "")
    url = paper.get("url", "") or f"https://arxiv.org/abs/{paper.get('arxiv_id', '')}"
    venue = paper.get("venue", "")
    sf_id = paper.get("sf_id", "")
    source = paper.get("source", "")

    # Determine item type
    if doi:
        item_type = "journalArticle"
    elif any(kw in venue.lower() for kw in ["conf", "workshop", "proceedings"]):
        item_type = "conferencePaper"
    else:
        item_type = "preprint"  # Zotero 9+ supports 'preprint' type

    # Build tags (may be dropped if Zotero "Automatic Tags" pref is OFF)
    tags = [{"tag": "hfpclawer", "type": 1}]
    if source and source.startswith("cron:"):
        domain = source.replace("cron:", "")
        tags.append({"tag": f"hfpclawer:{domain}", "type": 1})

    # Extra field ALWAYS survives — primary tracking mechanism
    extra_parts = []
    if sf_id:
        extra_parts.append(f"hfpclawer_id: {sf_id}")
    if paper.get("arxiv_id"):
        extra_parts.append(f"arXiv: {paper['arxiv_id']}")
    if paper.get("relevance"):
        extra_parts.append(f"hfpclawer_relevance: {paper['relevance']}")

    # Add source domain to extra for reliable tracking
    if source:
        extra_parts.append(f"hfpclawer_source: {source}")

    extra = "\n".join(extra_parts)

    item: dict[str, Any] = {
        "itemType": item_type,
        "title": title,
        "tags": tags,
        "extra": extra,
        "url": url,
        "date": "",
        "abstractNote": abstract,
    }

    if doi:
        item["DOI"] = doi

    if venue:
        item["publicationTitle"] = venue

    return item


def _make_session_id() -> str:
    """Generate a unique session ID for Connector protocol."""
    return f"hfpclawer-{uuid.uuid4().hex[:16]}"
