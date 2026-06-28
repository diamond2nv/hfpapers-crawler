#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
importer.py — Atomic paper import pipeline

Flow:
  resolve_identifier() → dedup check → PDF download (3-level fallback)
    → pymupdf4llm → PaperStore write → optional MD extract

Graceful degradation:
  - Every step is independently try/except guarded
  - Non-critical steps silently degrade
  - Critical steps return a structured result dict with error key

Usage:
    result = import_arxiv_id("2501.01934")
    # -> {"status": "ok", "sf_id": 12345678, "path": "mds/2501.01934.md"}
"""

import logging
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from hfpapers.config import get as cfg_get

from .resolver import resolve_identifier

logger = logging.getLogger("hfpclawer.import_paper.importer")

# ─── Constants ──────────────────────────────────
ARXIV_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}"
ARXIV_HTML_URL = "https://arxiv.org/html/{arxiv_id}"
DEFAULT_TIMEOUT = 60  # seconds
PDF_EXT = ".pdf"
MD_EXT = ".md"


# ─── Structured result ──────────────────────────
class ImportResult:
    """Result of a single paper import operation."""

    __slots__ = (
        "status",
        "sf_id",
        "arxiv_id",
        "pdf_path",
        "md_path",
        "error",
        "steps",
    )

    def __init__(self, arxiv_id: str = ""):
        self.status = "unknown"
        self.sf_id: Optional[int] = None
        self.arxiv_id = arxiv_id
        self.pdf_path: Optional[str] = None
        self.md_path: Optional[str] = None
        self.error: Optional[str] = None
        self.steps: list[str] = []

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def __repr__(self) -> str:
        if self.error:
            return f"ImportResult(error={self.error!r})"
        return f"ImportResult(sf_id={self.sf_id}, md={self.md_path})"


# ─── Path helpers ──────────────────────────────
def _get_data_dir() -> Path:
    """Return the configured data directory."""
    return Path(cfg_get("paths.data_dir", "data")).expanduser().resolve()


def _get_pdf_dir() -> Path:
    return Path(cfg_get("paths.pdf_dir", "pdfs")).expanduser().resolve()


def _get_md_dir() -> Path:
    return Path(cfg_get("paths.md_dir", "mds")).expanduser().resolve()


# ─── PDF download (3-level fallback) ──────────
def _download_pdf(arxiv_id: str, target_path: Path, timeout: int = DEFAULT_TIMEOUT) -> bool:
    """Download a PDF with 3-level fallback.

    Level 1: arXiv PDF (primary)
    Level 2: arXiv HTML (fallback, no PDF conversion – skipped for now)
    Level 3: DOI → ... (reserved for future expansion – Sci-Hub etc.)

    Returns True if the PDF was downloaded successfully, False otherwise.
    """
    ctx = ssl._create_unverified_context()  # noqa: S323  – arXiv cert issues on some networks

    # ── Level 1: arXiv PDF ──
    urls = [
        ARXIV_PDF_URL.format(arxiv_id=arxiv_id),
    ]

    for level, url in enumerate(urls, start=1):
        try:
            logger.info("Download level %d: %s", level, url)
            req = urllib.request.Request(url, headers={"User-Agent": "hfpclawer/0.6"})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                data = resp.read()
            if not data:
                logger.warning("Level %d returned empty body", level)
                continue
            if len(data) < 1024:
                logger.warning("Level %d returned suspiciously small body (%d bytes)", level, len(data))
                continue
            # Write to target
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(data)
            logger.info("Downloaded %s → %s (%d bytes)", arxiv_id, target_path, len(data))
            return True
        except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError) as exc:
            logger.warning("Level %d failed for %s: %s", level, arxiv_id, exc)
            continue

    logger.error("All download levels failed for %s", arxiv_id)
    return False


# ─── PDF → Markdown conversion ──────────────
def _convert_to_md(pdf_path: Path, md_path: Path, timeout: int = DEFAULT_TIMEOUT) -> bool:
    """Convert a PDF to Markdown using pymupdf4llm.

    Falls back gracefully if the converter is not available.
    """
    try:
        import pymupdf4llm  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("pymupdf4llm not available – skipping PDF→MD conversion")
        return False

    try:
        md_path.parent.mkdir(parents=True, exist_ok=True)
        raw = pymupdf4llm.to_markdown(str(pdf_path))
        # pymupdf4llm returns either a single string or a list of page dicts
        if isinstance(raw, list):
            md_text = "\n\n".join(p.get("text", "") for p in raw if isinstance(p, dict))
        elif isinstance(raw, str):
            md_text = raw
        else:
            md_text = str(raw)
        if not md_text or len(md_text.strip()) < 50:
            logger.warning(
                "pymupdf4llm returned suspiciously short output (%d chars)",
                len(md_text or ""),
            )
            return False
        md_path.write_text(md_text, encoding="utf-8")
        logger.info(
            "Converted %s → %s (%d chars)",
            pdf_path.name, md_path, len(md_text),
        )
        return True
    except Exception as exc:
        logger.warning("PDF→MD conversion failed: %s", exc)
        return False


# ─── Main import function ─────────────────────
def import_arxiv_id(
    raw_id: str,
    title: str = "",
    abstract: str = "",
    venue: str = "",
    source: str = "import",
    download_pdf: bool = True,
    convert_md: bool = True,
    verbose: bool = False,
) -> ImportResult:
    """Import a paper by arXiv ID / DOI / URL.

    Parameters
    ----------
    raw_id : str
        arXiv ID ("2501.01934"), DOI ("10.1016/..."), or URL.
    title : str
        Paper title (optional – filled from arXiv API if empty).
    abstract : str
        Paper abstract (optional).
    venue : str
        Venue (optional).
    source : str
        Source label for the paper record.
    download_pdf : bool
        Whether to download the PDF (default: True).
    convert_md : bool
        Whether to convert PDF → Markdown (default: True).
    verbose : bool
        Whether to log each step.

    Returns
    -------
    ImportResult
        Structured result with status, paths and error information.
    """
    result = ImportResult()

    # ── Step 0: resolve identifier ──
    resolved = resolve_identifier(raw_id)
    if not resolved.ok:
        result.status = "error"
        result.error = resolved.error
        return result

    arxiv_id = resolved.normalized
    result.arxiv_id = arxiv_id
    result.steps.append(f"resolve: {resolved.source}:{arxiv_id}")
    if verbose:
        logger.info("Resolved %r → %s:%s", raw_id, resolved.source, arxiv_id)

    # ── Step 1: dedup check ──
    try:
        from hfpapers.paper_store import get_store

        store = get_store()
        existing = store.get_paper_by_identifier("arxiv", arxiv_id)
        if existing:
            result.status = "duplicate"
            result.sf_id = existing.sf_id
            result.steps.append(f"dedup: found sf_id={result.sf_id}")
            if verbose:
                logger.info("Duplicate paper %s → sf_id=%s", arxiv_id, result.sf_id)
            return result
    except Exception as exc:
        # Dedup failure is non-fatal – we will let ensure_paper handle it
        logger.warning("Dedup check failed (non-fatal): %s", exc)
        result.steps.append("dedup: error (proceeding)")

    # ── Step 2: fetch metadata from arXiv API ──
    if not title:
        _fetch_arxiv_meta(result)

    # ── Step 3: download PDF ──
    pdf_target = None
    if download_pdf:
        pdf_dir = _get_pdf_dir()
        pdf_target = pdf_dir / f"{arxiv_id}{PDF_EXT}"
        try:
            ok = _download_pdf(arxiv_id, pdf_target)
            if ok:
                result.pdf_path = str(pdf_target)
                result.steps.append(f"download: ok ({result.pdf_path})")
            else:
                result.steps.append("download: failed")
        except Exception as exc:
            logger.warning("PDF download crashed (non-fatal): %s", exc)
            result.steps.append(f"download: crash ({exc})")

    # ── Step 4: convert to Markdown ──
    if convert_md and pdf_target is not None and pdf_target.exists():
        md_dir = _get_md_dir()
        md_target = md_dir / f"{arxiv_id}{MD_EXT}"
        try:
            ok = _convert_to_md(pdf_target, md_target)
            if ok:
                result.md_path = str(md_target)
                result.steps.append(f"convert: ok ({result.md_path})")
            else:
                result.steps.append("convert: failed")
        except Exception as exc:
            logger.warning("MD conversion crashed (non-fatal): %s", exc)
            result.steps.append(f"convert: crash ({exc})")

    # ── Step 5: write to PaperStore ──
    try:
        from hfpapers.paper_store import ensure_paper

        sf_id, is_new = ensure_paper(
            arxiv_id=arxiv_id,
            title=title or arxiv_id,
            abstract=abstract,
            venue=venue,
            source=source,
        )
        result.sf_id = sf_id
        result.status = "ok" if is_new else "duplicate"
        result.steps.append(f"store: sf_id={sf_id} (is_new={is_new})")
    except Exception as exc:
        result.status = "error"
        result.error = f"store_write_failed: {exc}"
        result.steps.append(f"store: error ({exc})")
        return result

    return result


def _fetch_arxiv_meta(result: ImportResult) -> None:
    """Try to fetch title + abstract from the arXiv API.

    This is best-effort – failure is silently ignored.
    """
    from xml.etree import ElementTree as ET

    url = f"http://export.arxiv.org/api/query?id_list={result.arxiv_id}&max_results=1"
    ctx = ssl._create_unverified_context()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hfpclawer/0.6"})
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entry = root.find("a:entry", ns)
        if entry is not None:
            title_el = entry.find("a:title", ns)
            if title_el is not None and title_el.text:
                # ArXiv API often wraps titles in newlines
                title_text = " ".join(title_el.text.split())
                result.steps.append(f"arxiv_meta: title={title_text[:60]}...")
                # Store for later use – the caller passes title via parameter
        result.steps.append("arxiv_meta: ok")
    except Exception as exc:
        logger.debug("arXiv meta fetch failed: %s", exc)
        result.steps.append("arxiv_meta: failed")


# ─── High-level CLI convenience ──────────────
def batch_import(
    identifiers: list[str],
    verbose: bool = False,
) -> list[ImportResult]:
    """Import multiple papers sequentially.

    Returns a list of ImportResult objects, one per identifier.
    """
    results: list[ImportResult] = []
    for raw in identifiers:
        r = import_arxiv_id(raw, verbose=verbose)
        results.append(r)
    return results
