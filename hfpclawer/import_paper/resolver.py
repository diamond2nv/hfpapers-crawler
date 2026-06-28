#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
resolver.py — Unified identifier resolver

Resolves arXiv ID / DOI / URL to a canonical (source, id) pair.
Each resolver is independent (try/except guard) so one failing source
does not block others.

Usage:
    result = resolve_identifier("2501.01934")
    # -> {"id": "2501.01934", "source": "arxiv", "normalized": "2501.01934"}

    result = resolve_identifier("10.1016/j.jcp.2025.114432")
    # -> {"id": "10.1016/j.jcp.2025.114432", "source": "doi", "normalized": "10.1016/j.jcp.2025.114432"}

    result = resolve_identifier("https://arxiv.org/abs/2501.01934")
    # -> {"id": "2501.01934", "source": "arxiv", "normalized": "2501.01934"}
"""

import logging
import re

logger = logging.getLogger("hfpclawer.import_paper.resolver")

# ─── Regex patterns ──────────────────────────────
ARXIV_ABS_RE = re.compile(
    r"(?:https?://)?(?:www\.)?arxiv\.org/abs/(\d{4}\.\d{4,5})(?:v\d+)?"
)
ARXIV_PDF_RE = re.compile(
    r"(?:https?://)?(?:www\.)?arxiv\.org/pdf/(\d{4}\.\d{4,5})(?:v\d+)?"
)
ARXIV_ID_RE = re.compile(r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b")
DOI_RE = re.compile(r"10\.\d{4,}/[^\s]+")


class ResolveResult:
    """Normalised resolution result."""

    __slots__ = ("id", "source", "normalized", "error")

    def __init__(
        self,
        id: str = "",
        source: str = "",
        normalized: str = "",
        error: str = "",
    ):
        self.id = id
        self.source = source
        self.normalized = normalized
        self.error = error

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.id)

    def __repr__(self) -> str:
        if self.error:
            return f"ResolveResult(error={self.error!r})"
        return f"ResolveResult({self.source}:{self.normalized})"


def _resolve_arxiv(raw: str) -> ResolveResult:
    """Try to extract an arXiv ID from the input."""
    for pat in (ARXIV_ABS_RE, ARXIV_PDF_RE, ARXIV_ID_RE):
        m = pat.search(raw.strip())
        if m:
            aid = m.group(1)
            return ResolveResult(id=aid, source="arxiv", normalized=aid)
    return ResolveResult(error="not_arxiv")


def _resolve_doi(raw: str) -> ResolveResult:
    """Try to extract a DOI from the input."""
    m = DOI_RE.search(raw.strip())
    if m:
        doi = m.group(0).rstrip(".,;:!?")
        return ResolveResult(id=doi, source="doi", normalized=doi)
    return ResolveResult(error="not_doi")


def resolve_identifier(raw: str) -> ResolveResult:
    """Unified entry point: try each resolver in priority order.

    Priority: arXiv → DOI

    The first successful resolution wins.  Each resolver is guarded
    independently so a malformed input never crashes the pipeline.
    """
    if not raw or not raw.strip():
        return ResolveResult(error="empty_input")

    try:
        # arXiv first (most common for this toolchain)
        result = _resolve_arxiv(raw)
        if result.ok:
            return result

        # DOI second
        result = _resolve_doi(raw)
        if result.ok:
            return result

        return ResolveResult(error=f"unrecognised_identifier: {raw[:80]!r}")
    except Exception as exc:
        logger.exception("resolve_identifier crashed")
        return ResolveResult(error=f"resolve_crash: {exc}")
