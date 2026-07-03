#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hfpclawer.audit — Unified citation traceability and verification package.

Submodules:
  bib          BibTeX parsing + arXiv/DOI metadata verification
  store        Cross-store JSONL reference matching
  notebook     Jupyter notebook citation extraction
  traceability Full-chain traceability engine
  report       Audit report generation
  l1_local     L1: Local SQLite existence check
  l2_s2        L2: Semantic Scholar API client
  l3_openalex   L3: OpenAlex API client
  similarity   Title normalization and similarity scoring

Quick start:
    from hfpclawer.audit import run_traceability
    report = run_traceability(
        bib_path="data/references/references.bib",
        cross_stores={"coc": "data/references/refs.jsonl"},
        notebook_dirs=["notebooks/"],
    )
    print(report["summary"])
"""

from hfpclawer.audit.traceability import run_traceability, cli_run
from hfpclawer.audit.bib import parse_bib, verify_bib_entry, BibEntry, BibVerification
from hfpclawer.audit.store import load_jsonl_store, check_in_stores
from hfpclawer.audit.notebook import extract_notebook_citations, scan_notebook_dirs
from hfpclawer.audit.report import generate_report, write_report, print_summary
from hfpclawer.audit.l1_local import check_citation_local, find_arxiv_db
from hfpclawer.audit.l2_s2 import S2Client
from hfpclawer.audit.l3_openalex import OAClient
from hfpclawer.audit.similarity import normalize_title, title_similarity, exact_match

__all__ = [
    "run_traceability", "cli_run",
    "parse_bib", "verify_bib_entry", "BibEntry", "BibVerification",
    "load_jsonl_store", "check_in_stores",
    "extract_notebook_citations", "scan_notebook_dirs",
    "generate_report", "write_report", "print_summary",
    "check_citation_local", "find_arxiv_db",
    "S2Client", "OAClient",
    "normalize_title", "title_similarity", "exact_match",
]
