#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""store.py — Cross-store reference matching (JSONL).

Port of coc citation_traceability.py JSONL loading + cross-matching.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("hfpclawer.audit.store")


def normalise_arxiv_id(raw: str) -> str:
    s = raw.strip().lower()
    s = re.sub(r"^arxiv:", "", s)
    s = re.sub(r"v\d+$", "", s)
    return s


def load_jsonl_store(path: Path) -> dict[str, set[str]]:
    """Load arXiv IDs (arxiv:XXXX.XXXXX) and DOIs (doi:10.xxx/...) from a JSONL store.

    Returns dict with keys "arxiv" and "doi", each containing a set of identifiers.
    """
    result: dict[str, set[str]] = {"arxiv": set(), "doi": set()}
    if not path.exists():
        logger.warning("Store not found: %s", path)
        return result

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            aid = data.get("arxiv_id", "") or data.get("eprint", "") or ""
            if aid:
                result["arxiv"].add(normalise_arxiv_id(aid))
            doi = data.get("doi", "")
            if doi:
                result["doi"].add(doi.strip().lower())

    logger.info("Loaded %s: %d arXiv, %d DOI", path.name, len(result["arxiv"]), len(result["doi"]))
    return result


def check_in_stores(
    arxiv_id: str = "",
    doi: str = "",
    stores: Optional[dict[str, dict[str, set[str]]]] = None,
) -> dict[str, bool]:
    """Check if a reference exists in cross-stores.

    Returns {store_label: True/False}.
    """
    if not stores:
        return {}
    result: dict[str, bool] = {}
    for label, ids in stores.items():
        found = False
        if arxiv_id and normalise_arxiv_id(arxiv_id) in ids.get("arxiv", set()):
            found = True
        if doi and doi.strip().lower() in ids.get("doi", set()):
            found = True
        result[label] = found
    return result
