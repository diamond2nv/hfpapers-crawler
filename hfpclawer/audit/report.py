#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report.py — Audit report generation and formatting.

Produces standardized JSON audit reports with summary stats and cross-reference matrices.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("hfpclawer.audit.report")


def generate_report(
    repo_name: str = "unknown",
    entries: list[dict[str, Any]] | None = None,
    layers_used: list[str] | None = None,
    store_labels: list[str] | None = None,
) -> dict[str, Any]:
    """Generate a standardized audit report from verified entries."""
    if entries is None:
        entries = []
    if layers_used is None:
        layers_used = []
    if store_labels is None:
        store_labels = []

    stats = {
        "total": len(entries),
        "verified": 0,
        "no_identifier": 0,
        "in_store_counts": {label: 0 for label in store_labels},
        "in_notebooks": 0,
        "bib_matched": 0,
    }

    for e in entries:
        if e.get("verified", False):
            stats["verified"] += 1
        if not e.get("arxiv_id") and not e.get("doi"):
            stats["no_identifier"] += 1
        if e.get("citing_notebooks"):
            stats["in_notebooks"] += 1
        if e.get("bib_verified", False):
            stats["bib_matched"] += 1

        for label in store_labels:
            in_store = e.get("in_stores", {}).get(label, False)
            if in_store:
                stats["in_store_counts"][label] += 1

    # Cross-reference matrix
    matrix: dict[str, int] = {}
    if len(store_labels) >= 2:
        for combo in _get_combinations(store_labels, entries):
            matrix[combo["label"]] = combo["count"]

    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": repo_name,
        "layers_used": layers_used,
        "summary": {
            "total": stats["total"],
            "verified": stats["verified"],
            "no_identifier": stats["no_identifier"],
            "in_notebooks": stats["in_notebooks"],
            "bib_verified": stats["bib_matched"],
            **stats["in_store_counts"],
        },
        "cross_reference_matrix": matrix,
        "citations": entries,
    }

    return report


def _get_combinations(labels: list[str], entries: list[dict]) -> list[dict]:
    """Build cross-reference matrix (e.g. coc_only, fusion_only, both)."""
    from itertools import combinations

    result = []
    for n in range(1, len(labels) + 1):
        for combo in combinations(labels, n):
            label = "_and_".join(combo)
            count = 0
            for e in entries:
                in_stores = e.get("in_stores", {})
                all_match = all(in_stores.get(l, False) for l in combo)
                others_match = any(in_stores.get(l, False) for l in labels if l not in combo)
                if all_match and not others_match:
                    count += 1
            result.append({"label": f"{label}_only", "count": count})

    # both / neither
    both = sum(1 for e in entries if all(e.get("in_stores", {}).get(l, False) for l in labels))
    neither = sum(1 for e in entries if not any(e.get("in_stores", {}).get(l, False) for l in labels))
    result.append({"label": "all_stores", "count": both})
    result.append({"label": "none", "count": neither})

    return result


def write_report(report: dict, path: str) -> None:
    """Write report to JSON file."""
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Report written to %s", p)


def print_summary(report: dict) -> None:
    """Print a human-readable summary to stdout."""
    s = report.get("summary", {})
    matrix = report.get("cross_reference_matrix", [])
    print(f"\n{'='*60}")
    print(f"  Audit Report — {report.get('repo', 'unknown')}")
    print(f"  Layers: {', '.join(report.get('layers_used', []))}")
    print(f"{'='*60}")
    print(f"  Total citations:    {s.get('total', 0)}")
    print(f"  ✅ Bib verified:    {s.get('bib_verified', 0)}")
    print(f"  📦 In store:        {s.get('in_store_counts', {})}")
    print(f"  📓 In notebooks:    {s.get('in_notebooks', 0)}")
    print(f"  ❌ No identifier:   {s.get('no_identifier', 0)}")
    if matrix:
        print(f"  ── Cross-ref matrix ──")
        for m in matrix:
            print(f"    {m['label']}: {m['count']}")
    print(f"{'='*60}")
