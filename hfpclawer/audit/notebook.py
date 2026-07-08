#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notebook.py — Extract citations from Jupyter notebooks (.ipynb).

Scans for arXiv IDs and DOIs in notebook markdown/code cells.
"""

import logging
import re
from pathlib import Path

from hfpclawer.audit.store import normalise_arxiv_id

logger = logging.getLogger("hfpclawer.audit.notebook")

ARXIV_PATTERN = re.compile(
    r'(?:arXiv\s*:\s*(\d{4}\.\d+)|arxiv\.org/(?:abs|pdf)/(\d{4}\.\d+))',
    re.IGNORECASE,
)
DOI_PATTERN = re.compile(
    r'(?:DOI\s*:\s*(10\.\d{4,}/\S+)|doi\.org/(10\.\d{4,}/\S+))',
    re.IGNORECASE,
)


def extract_notebook_citations(dir_paths: list[Path]) -> dict[str, list[str]]:
    """Scan .ipynb files for arXiv IDs and DOIs.

    Returns: {arxiv_id_or_doi: [notebook_names]}
    """
    citations: dict[str, list[str]] = {}

    for nb_dir in dir_paths:
        if not nb_dir.exists():
            continue
        for nb_file in sorted(nb_dir.glob("*.ipynb")):
            try:
                text = nb_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            for match in ARXIV_PATTERN.finditer(text):
                aid = (match.group(1) or match.group(2) or "").strip()
                if aid:
                    aid = normalise_arxiv_id(aid)
                    citations.setdefault(f"arxiv:{aid}", []).append(nb_file.name)

            for match in DOI_PATTERN.finditer(text):
                doi = (match.group(1) or match.group(2) or "").strip().lower()
                if doi:
                    citations.setdefault(f"doi:{doi}", []).append(nb_file.name)

    return citations


def scan_notebook_dirs(
    candidates: list[Path],
    arxiv_id: str = "",
    doi: str = "",
) -> list[str]:
    """Check if a specific reference appears in any notebook."""
    all_citations = extract_notebook_citations(candidates)
    citing: list[str] = []

    if arxiv_id:
        key = f"arxiv:{normalise_arxiv_id(arxiv_id)}"
        citing.extend(all_citations.get(key, []))

    if doi:
        key = f"doi:{doi.strip().lower()}"
        citing.extend(all_citations.get(key, []))

    return list(set(citing))
