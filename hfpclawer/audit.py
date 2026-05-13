#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit.py — Data source audit module

Provides:
  - run_audit(): Generate full audit report
  - cli_audit(): CLI entry point
"""

import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from hfpapers.config import get as cfg_get

logger = logging.getLogger("hfpclawer.audit")


def _get_db_path() -> str:
    """Get arxiv_meta.db path"""
    base = cfg_get("db.path", "data/arxiv_meta.db")
    if not os.path.isabs(base):
        base = os.path.join(os.getcwd(), base)
    return base


def _get_data_dir() -> str:
    """Get data directory path"""
    data_dir = cfg_get("paths.data_dir", "data")
    if not os.path.isabs(data_dir):
        data_dir = os.path.join(os.getcwd(), data_dir)
    return data_dir


def _get_state_paths(db_dir: str) -> list[dict]:
    """Scan download_state JSON fallback files"""
    results = []
    for f in sorted(Path(db_dir).glob("*_download_state.json")):
        try:
            with open(f) as fp:
                state = json.load(fp)
            results.append({
                "file": str(f),
                "source": state.get("source", f.stem.replace("_download_state", "")),
                "status": state.get("status", "unknown"),
                "total_new": state.get("total_new", 0),
                "total_fetched": state.get("total_fetched", 0),
                "last_update": state.get("last_update", ""),
                "checksum": state.get("checksum", ""),
                "error": state.get("error", ""),
            })
        except (json.JSONDecodeError, OSError) as e:
            results.append({
                "file": str(f),
                "source": "unknown",
                "status": f"parse_error: {e}",
            })
    return results


def _get_jsonl_info(data_dir: str) -> Optional[dict]:
    """Check arxiv_metadata.jsonl file status"""
    jsonl_path = Path(data_dir) / "arxiv_metadata.jsonl"
    if jsonl_path.exists():
        size_mb = jsonl_path.stat().st_size / (1024 * 1024)
        line_count = 0
        for _ in open(jsonl_path, "rb"):
            line_count += 1
        return {
            "exists": True,
            "path": str(jsonl_path),
            "size_mb": round(size_mb, 1),
            "lines": line_count,
        }
    return {"exists": False, "path": str(jsonl_path)}


def run_paper_store_audit(store=None) -> dict:
    """Audit paper_store paper quality (cross-validation, identifier distribution)

    Args:
        store: PaperStore instance, None uses get_store()

    Returns:
        dict with keys:
        - total_papers: Total papers count
        - verified_papers: Verified papers count
        - with_code: Papers with code count
        - dual_id_papers: Papers with both arXiv + DOI identifiers
        - identifier_types: List of all identifier types
        - identifier_type_stats: [{type, count}, ...]
    """
    if store is None:
        from hfpapers.paper_store import get_store
        store = get_store()

    stats = store.stats()
    report = {
        "total_papers": stats["papers_total"],
        "verified_papers": stats["papers_verified"],
        "with_code": stats["papers_with_code"],
        "dual_id_papers": 0,
        "identifier_types": list(stats.get("identifiers_by_type", {}).keys()),
        "identifier_type_stats": [
            {"type": t, "count": c}
            for t, c in stats.get("identifiers_by_type", {}).items()
        ],
    }

    # Calculate dual_id_papers: papers with both arxiv and doi identifiers
    if report["total_papers"] > 0:
        with store._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) FROM (
                    SELECT p.sf_id FROM papers p
                    JOIN identifiers i1 ON p.sf_id = i1.sf_id AND i1.id_type = 'arxiv'
                    JOIN identifiers i2 ON p.sf_id = i2.sf_id AND i2.id_type = 'doi'
                    GROUP BY p.sf_id
                )
            """).fetchone()
            report["dual_id_papers"] = row[0] if row else 0

    # Supplement: verified ratio
    if report["total_papers"] > 0:
        report["verified_ratio"] = round(report["verified_papers"] / report["total_papers"], 4)
        report["dual_id_ratio"] = round(report["dual_id_papers"] / report["total_papers"], 4)
    else:
        report["verified_ratio"] = 0.0
        report["dual_id_ratio"] = 0.0

    return report


def run_full_audit(db_path: str = None, data_dir: str = None) -> dict:
    """Full audit: arxiv_meta data source audit + paper_store paper quality audit"""
    meta_report = run_audit(db_path=db_path, data_dir=data_dir)
    store_report = run_paper_store_audit()
    return {
        "timestamp": meta_report["timestamp"],
        "arxiv_meta": meta_report,
        "paper_store": store_report,
    }


def format_paper_store_report(report: dict) -> str:
    """Format as readable text"""
    lines = []
    lines.append("\n📚 Paper Store Paper Quality:")
    lines.append(f"  Total papers: {report['total_papers']:,}")
    lines.append(f"  Verified:     {report['verified_papers']:,} ({report.get('verified_ratio', 0)*100:.1f}%)")
    lines.append(f"  With code:    {report['with_code']:,}")
    lines.append(f"  Dual ID:      {report['dual_id_papers']:,} ({report.get('dual_id_ratio', 0)*100:.1f}%)")

    lines.append("\n  Identifier distribution:")
    for ts in report.get("identifier_type_stats", []):
        lines.append(f"    {ts['type']}: {ts['count']:,}")

    return "\n".join(lines)


def format_full_audit_report(report: dict) -> str:
    """Full audit report"""
    lines = []
    lines.append("=" * 50)
    lines.append("📊 Full Data Audit Report")
    lines.append(f"Time: {report['timestamp']}")
    lines.append("=" * 50)
    lines.append("")

    # arxiv_meta section
    meta = report.get("arxiv_meta", {})
    lines.append("📁 Metadata Source (arxiv_meta.db)")
    lines.append(f"  DB: {meta.get('db_path', 'N/A')}")
    lines.append(f"  Exists: {'✅' if meta.get('db_exists') else '❌'}")
    if meta.get("db_exists"):
        size = os.path.getsize(meta["db_path"]) / (1024 * 1024)
        lines.append(f"  Size: {size:.0f} MB")
        lines.append(f"  Total: {meta.get('total', 0):,} papers")
        lines.append(f"  source column: {'✅' if meta.get('has_source_column') else '❌'}")

        lines.append("\n  Data sources:")
        for src, info in meta.get("sources", {}).items():
            label = "legacy" if src == "unknown" else src
            lines.append(f"    [{label}] {info['count']:,} papers")
            if info.get("first_import"):
                lines.append(f"      First import: {info['first_import']}")
            if info.get("last_import"):
                lines.append(f"      Last import: {info['last_import']}")

    # state files
    state_files = meta.get("state_files", [])
    if state_files:
        lines.append("\n  State files:")
        for sf in state_files:
            lines.append(f"    {Path(sf['file']).name} → {sf['status']} ({sf['total_new']:,} papers)")

    # JSONL
    jl = meta.get("jsonl", {})
    if jl:
        lines.append(f"\n  Kaggle JSONL: {'✅ ' + jl.get('path','') if jl.get('exists') else '❌ Does not exist'}")

    # paper_store section
    lines.append("")
    ps = report.get("paper_store", {})
    lines.append(format_paper_store_report(ps))

    return "\n".join(lines)


def run_audit(db_path: str = None, data_dir: str = None) -> dict:
    """Run audit, return full report dict"""
    db_path = db_path or _get_db_path()
    data_dir = data_dir or _get_data_dir()

    report = {
        "timestamp": datetime.now().isoformat(),
        "db_path": db_path,
        "data_dir": data_dir,
        "db_exists": os.path.exists(db_path),
        "sources": {},
        "state_files": [],
        "jsonl": None,
        "total": 0,
    }

    if not report["db_exists"]:
        return report

    # Connect DB
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        # Check if source column exists
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(arxiv_meta)").fetchall()]
        has_source = "source" in cols
        report["has_source_column"] = has_source

        if has_source:
            # Per-source stats
            rows = conn.execute(
                "SELECT source, COUNT(*) as cnt, MIN(imported_at) as first_import, "
                "MAX(imported_at) as last_import FROM arxiv_meta GROUP BY source"
            ).fetchall()
            for r in rows:
                report["sources"][r["source"] if r["source"] else "unknown"] = {
                    "count": r["cnt"],
                    "first_import": r["first_import"],
                    "last_import": r["last_import"],
                }

        # Total
        report["total"] = conn.execute("SELECT COUNT(*) FROM arxiv_meta").fetchone()[0]

        # Fallback when no source column
        if not has_source:
            report["sources"]["legacy"] = {"count": report["total"], "note": "No source column, all data marked as legacy"}
    finally:
        conn.close()

    # state files
    db_dir = os.path.dirname(db_path)
    report["state_files"] = _get_state_paths(db_dir)

    # JSONL check
    report["jsonl"] = _get_jsonl_info(data_dir)

    return report


def format_audit_report(report: dict) -> str:
    """Format as readable text"""
    lines = []
    lines.append("=" * 50)
    lines.append("📊 Data Source Audit Report")
    lines.append(f"Time: {report['timestamp']}")
    lines.append("=" * 50)
    lines.append("")

    # DB
    lines.append(f"📁 Database: {report['db_path']}")
    lines.append(f"   Exists: {'✅' if report['db_exists'] else '❌'}")
    if report["db_exists"]:
        size = os.path.getsize(report["db_path"]) / (1024 * 1024)
        lines.append(f"   Size: {size:.0f} MB")
        lines.append(f"   Total: {report['total']:,} papers")

    if not report["db_exists"]:
        return "\n".join(lines)

    # Per-source
    lines.append(f"\n   source column: {'✅' if report.get('has_source_column') else '❌'}")
    lines.append("\n📂 Data Sources:")
    for src, info in report.get("sources", {}).items():
        label = "legacy" if src == "unknown" else src
        lines.append(f"  [{label}]")
        lines.append(f"    Papers: {info['count']:,}")
        if info.get("first_import"):
            lines.append(f"    First import: {info['first_import']}")
        if info.get("last_import"):
            lines.append(f"    Last import: {info['last_import']}")
        if info.get("note"):
            lines.append(f"    Note: {info['note']}")

    # state files
    lines.append("\n📄 State files (download_state backup):")
    for sf in report.get("state_files", []):
        lines.append(f"  📍 {Path(sf['file']).name}")
        lines.append(f"     Source: {sf['source']}")
        lines.append(f"     Status: {sf['status']}")
        if sf.get("total_new"):
            lines.append(f"     Papers: {sf['total_new']:,}")
        if sf.get("last_update"):
            lines.append(f"     Last update: {sf['last_update']}")
        if sf.get("checksum"):
            lines.append(f"     checksum: {sf['checksum'][:20]}...")
        if sf.get("error"):
            lines.append(f"     ⚠️ Error: {sf['error']}")

    if not report.get("state_files"):
        lines.append("  No state files")

    # JSONL
    jl = report.get("jsonl", {})
    lines.append("\n📦 Kaggle JSONL File:")
    if jl.get("exists"):
        lines.append(f"  ✅ Exists: {jl['path']}")
        lines.append(f"     Size: {jl['size_mb']} MB")
        lines.append(f"     Lines: {jl['lines']:,}")
    else:
        lines.append("  ❌ Does not exist")

    return "\n".join(lines)
