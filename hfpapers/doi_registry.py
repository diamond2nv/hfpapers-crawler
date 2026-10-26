#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# doi_registry.py
"""Is this DOI registered, and what does it actually point at?

Written for the write path (2026-09-25): the store's three wrong DOIs found in a full audit all
arrived from a caller that handed the identifier over and never looked it up — one of them does not
exist at all. ``resolve`` answers two questions in one call: *does a registry know this DOI*, and
*what title does it carry* (so the caller can compare it with the record it is being attached to).

Two registries, in order:

1. **Crossref** — journal articles and proceedings, the common case;
2. **DataCite** — arXiv's ``10.48550/…``, Zenodo's ``10.5281/…``, CNKI's ``10.19655/…`` and friends.

The second is not optional. A Crossref 404 is *not* evidence that a DOI is bogus: 20 of the live
store's 23 unattributable DOI titles are DataCite registrants, so a Crossref-only check would refuse
legitimate identifiers (the same mistake as the ``FETCH_FAIL`` bucket in the offline audit).

Statuses are a contract:

``("ok", work)``         a registry answered and ``work["title"]`` is what it holds
``("not_found", {})``    both registries answered 404 — the DOI is not registered
``("error", {...})``     at least one registry was unreachable and no registry said "no such DOI";
                         "could not check" is never reported as "wrong"
"""

from __future__ import annotations

import re

import requests

__all__ = ["resolve", "RESOLVE_STATUSES", "WORK_KEYS"]

RESOLVE_STATUSES = ("ok", "not_found", "error")
WORK_KEYS = ("doi", "title", "venue", "year", "registry", "type")

_CROSSREF = "https://api.crossref.org/works/"
_DATACITE = "https://api.datacite.org/dois/"
_UA = "HFPCrawler/1.0 (mailto:dev@example.com)"
_TAG_RE = re.compile(r"<[^>]{0,400}>")


def _plain_title(raw: object) -> str:
    """Crossref titles sometimes carry inline MathML; strip it so callers can compare titles."""
    if isinstance(raw, str):
        text = raw
    elif isinstance(raw, list):
        text = raw[0] if raw else ""
    else:
        text = ""
    return _TAG_RE.sub(" ", str(text or "")).strip()


def _crossref_year(item: dict) -> int:
    for key in ("published-print", "published-online", "issued", "created"):
        parts = (item.get(key) or {}).get("date-parts") or [[]]
        if parts and parts[0]:
            return parts[0][0]
    return 0


def _crossref(doi: str, timeout: int) -> tuple[str, dict]:
    try:
        resp = requests.get(f"{_CROSSREF}{doi}", headers={"User-Agent": _UA, "Accept": "application/json"},
                            timeout=timeout)
    except requests.RequestException as exc:  # connection-level: cannot check, not "wrong"
        return "error", {"reason": type(exc).__name__}
    if resp.status_code == 404:
        return "not_found", {}
    if resp.status_code != 200:
        return "error", {"reason": f"HTTP {resp.status_code}"}
    try:
        item = resp.json()["message"]
    except Exception as exc:  # noqa: BLE001 — a malformed body is not a verdict either
        return "error", {"reason": type(exc).__name__}
    return "ok", {
        "doi": doi,
        "title": _plain_title(item.get("title")),
        "venue": (item.get("container-title") or [""])[0],
        "year": _crossref_year(item),
        "registry": "crossref",
        "type": item.get("type", ""),
    }


def _datacite(doi: str, timeout: int) -> tuple[str, dict]:
    try:
        resp = requests.get(f"{_DATACITE}{doi}", headers={"User-Agent": _UA, "Accept": "application/json"},
                            timeout=timeout)
    except requests.RequestException as exc:
        return "error", {"reason": type(exc).__name__}
    if resp.status_code == 404:
        return "not_found", {}
    if resp.status_code != 200:
        return "error", {"reason": f"HTTP {resp.status_code}"}
    try:
        attrs = resp.json()["data"]["attributes"]
    except Exception as exc:  # noqa: BLE001
        return "error", {"reason": type(exc).__name__}
    return "ok", {
        "doi": doi,
        "title": _plain_title((attrs.get("titles") or [{}])[0].get("title", "")),
        "venue": (attrs.get("publisher") or ""),
        "year": int(attrs.get("publicationYear") or 0),
        "registry": "datacite",
        "type": (attrs.get("types") or {}).get("resourceTypeGeneral", ""),
    }


def resolve(doi: str, *, timeout: int = 20) -> tuple[str, dict]:
    """``("ok", work) | ("not_found", {}) | ("error", {...})`` — see the module docstring."""
    doi = (doi or "").strip()
    if not doi:
        return "not_found", {}
    status, work = _crossref(doi, timeout)
    if status != "not_found":
        return status, work
    # Crossref said "no such DOI" — let DataCite disagree before believing it.
    return _datacite(doi, timeout)
