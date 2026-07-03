#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""traceability.py — Full-chain citation traceability engine.

Combines: bib → store → notebook → L1/L2/L3 into a single pipeline.
Port of coc-inverse-agent scripts/citation_traceability.py.
"""

import logging
import time
from pathlib import Path
from typing import Any, Optional

from hfpclawer.audit import bib as audit_bib
from hfpclawer.audit import store as audit_store
from hfpclawer.audit import notebook as audit_notebook
from hfpclawer.audit import report as audit_report
from hfpclawer.audit.l1_local import check_citation_local, ARXIV_ID_RE
from hfpclawer.audit.l2_s2 import S2Client
from hfpclawer.audit.l3_openalex import OAClient

logger = logging.getLogger("hfpclawer.audit.traceability")


def run_traceability(
    bib_path: Optional[Path] = None,
    cross_stores: Optional[dict[str, Path]] = None,
    notebook_dirs: Optional[list[Path]] = None,
    repo_name: str = "auto",
    quick: bool = False,
    use_l2_l3: bool = False,
    output_path: Optional[str] = None,
) -> dict[str, Any]:
    """Full-chain citation traceability audit.

    Args:
        bib_path: Path to references.bib (auto-detect if None).
        cross_stores: {label: path_to_jsonl}.
        notebook_dirs: List of notebook directories.
        repo_name: Repository name for report.
        quick: Skip HTTP verifications.
        use_l2_l3: Also run L2/L3 API lookups.
        output_path: Write report to this JSON path.

    Returns:
        Audit report dict.
    """
    # ── 1. Parse BibTeX ──
    if bib_path is None:
        bib_path = _detect_bib()
    entries = audit_bib.parse_bib(bib_path) if bib_path else []
    logger.info("Parsed %d BibTeX entries from %s", len(entries), bib_path)

    # ── 2. Load cross-stores ──
    stores: dict[str, dict[str, set[str]]] = {}
    if cross_stores:
        for label, path in cross_stores.items():
            stores[label] = audit_store.load_jsonl_store(path)

    # ── 3. Scan notebooks ──
    nb_citations: dict[str, list[str]] = {}
    if notebook_dirs:
        nb_citations = audit_notebook.extract_notebook_citations(notebook_dirs)
        logger.info("Found %d notebook citation keys", len(nb_citations))

    # ── 4. Verify each entry ──
    results: list[dict[str, Any]] = []
    for i, entry in enumerate(entries):
        result: dict[str, Any] = {
            "cite_key": entry.cite_key,
            "title": entry.title[:100],
            "authors": entry.authors,
            "year": entry.year,
            "arxiv_id": entry.arxiv_id,
            "doi": entry.doi,
            "verified": False,
            "bib_verified": False,
            "in_stores": {},
            "citing_notebooks": [],
            "l1_status": "",
            "l2_status": "",
            "l3_status": "",
        }

        # Bib verification
        if entry.arxiv_id or entry.doi:
            v = audit_bib.verify_bib_entry(entry)
            result["bib_verified"] = v.success
            result["bib_source"] = v.source
            result["bib_matched"] = v.matched
            result["bib_mismatched"] = v.mismatched

        # Cross-store
        if stores:
            result["in_stores"] = audit_store.check_in_stores(
                arxiv_id=entry.arxiv_id, doi=entry.doi, stores=stores,
            )

        # Notebook
        if nb_citations:
            result["citing_notebooks"] = audit_notebook.scan_notebook_dirs(
                notebook_dirs or [],
                arxiv_id=entry.arxiv_id,
                doi=entry.doi,
            )

        # L1 local
        if entry.arxiv_id or entry.title:
            l1 = check_citation_local(
                title=entry.title,
                authors_hint=entry.authors[0] if entry.authors else "",
                year_hint=entry.year,
                arxiv_id=entry.arxiv_id,
            )
            result["l1_status"] = l1.get("status", "")

        # L2 S2 (optional, slower)
        if use_l2_l3 and entry.arxiv_id:
            try:
                s2 = S2Client()
                l2 = s2.lookup_by_arxiv(entry.arxiv_id) if entry.arxiv_id else s2.lookup(entry.title)
                result["l2_status"] = l2.get("status", "")
            except Exception:
                result["l2_status"] = "ERROR"

        # L3 OpenAlex (optional, slower)
        if use_l2_l3 and entry.arxiv_id:
            try:
                oa = OAClient()
                l3 = oa.lookup_by_arxiv(entry.arxiv_id) if entry.arxiv_id else oa.lookup(entry.title)
                result["l3_status"] = l3.get("status", "")
            except Exception:
                result["l3_status"] = "ERROR"

        # Overall: verified if bib matches OR in any store
        any_store = any(result["in_stores"].values()) if stores else False
        result["verified"] = result["bib_verified"] or any_store
        results.append(result)

    # ── 5. Generate report ──
    layers = ["bib"]
    if stores:
        layers.append("store")
    if notebook_dirs:
        layers.append("notebook")
    if use_l2_l3:
        layers.extend(["l1_local", "l2_s2", "l3_openalex"])

    report = audit_report.generate_report(
        repo_name=repo_name,
        entries=results,
        layers_used=layers,
        store_labels=list(stores.keys()) if stores else [],
    )

    if output_path:
        audit_report.write_report(report, output_path)

    return report


def _detect_bib() -> Optional[Path]:
    """Auto-detect references.bib in common locations."""
    cwd = Path.cwd()
    candidates = [
        cwd / "data" / "references" / "references.bib",
        cwd / "report" / "references.bib",
        cwd.parent / "coc-inverse-agent" / "data" / "references" / "references.bib",
        cwd.parent / "fusion-tech-intelligence" / "report" / "references.bib",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def cli_run(args: Any) -> int:
    """CLI entry point for 'hfpclawer audit traceability'."""
    bib = Path(args.bib) if args.bib else None

    stores = {}
    if args.stores:
        for kv in args.stores.split(","):
            if ":" in kv:
                label, path = kv.split(":", 1)
                stores[label] = Path(path).expanduser()

    notebooks = [Path(d).expanduser() for d in (args.notebook_dirs or "").split(",") if d] if args.notebook_dirs else None

    report = run_traceability(
        bib_path=bib,
        cross_stores=stores or None,
        notebook_dirs=notebooks,
        repo_name=args.repo or _detect_repo_name(),
        quick=args.quick,
        use_l2_l3=args.l2l3,
        output_path=args.output,
    )

    audit_report.print_summary(report)
    if args.json:
        print(__import__("json").dumps(report, indent=2, ensure_ascii=False))
    return 0


def _detect_repo_name() -> str:
    """Try to detect the current repository name."""
    cwd = Path.cwd()
    name = cwd.name
    if (cwd / "src" / "coc").exists():
        return "coc-inverse-agent"
    if (cwd / "report" / "chapters").exists():
        return "fusion-tech-intelligence"
    if (cwd / "hfpclawer").exists():
        return "hfpclawer"
    return name
