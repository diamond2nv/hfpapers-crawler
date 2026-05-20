#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
citation_audit.py — Citation Verification Engine (L3 Arch)

Three-tier architecture:

  L1: Local existence check     → "Does this cited paper exist in local DB?"
  L2: Semantic Scholar lookup   → "Does Semantic Scholar confirm it?"
  L3: OpenAlex lookup           → "Does OpenAlex confirm it?"

Orchestration: L1 → L2 (fallback) → L3 (final fallback).
Each tier independently reports "VERIFIED" | "SUSPECTED" | "NOT_FOUND" | "ERROR".

Parts adapted from academic-research-skills by Cheng-I Wu (CC BY-NC 4.0).
"""

import logging
import os
import re
from datetime import datetime
from typing import Literal, Optional

from hfpclawer._text_similarity import exact_match, title_similarity

logger = logging.getLogger("hfpclawer.citation_audit")

# ─── Types ──────────────────────────────────────────

CitationSource = Literal["local", "s2", "openalex", "auto"]
CitationStatus = Literal["VERIFIED", "SUSPECTED", "NOT_FOUND", "ERROR"]

AUDIT_SOURCES: list[CitationSource] = ["local", "s2", "openalex"]


# ─── Config ──────────────────────────────────────────

DEFAULT_DB_PATHS = [
    os.path.expanduser("~/Gitlab/Agentic4Sci/arxiv-metadata-service/data/arxiv_meta.db"),
    "data/arxiv_meta.db",
]

ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")

# Scoring thresholds (from ARS protocol, locked)
TITLE_SIMILARITY_THRESHOLD = 0.70


# ─── L1: Local Existence Check ───────────────────────


def find_arxiv_db() -> Optional[str]:
    """Find the local arxiv_meta.db (returns first existing path)."""
    for p in DEFAULT_DB_PATHS:
        if os.path.exists(p):
            return p
    return None


def _make_status(score: float) -> CitationStatus:
    """Convert a score [0,1] to a status label."""
    if score >= 0.70:
        return "VERIFIED"
    elif score >= 0.40:
        return "SUSPECTED"
    else:
        return "NOT_FOUND"


def check_citation_local(
    title: str,
    authors_hint: str = "",
    year_hint: int = 0,
    db_path: Optional[str] = None,
) -> dict:
    """L1: Check if a cited paper exists in local arxiv_meta.db FTS5.

    Returns dict with keys: status, title, matches (sorted by score).
    """
    db = db_path or find_arxiv_db()
    if not db:
        return {"status": "ERROR", "error": "arxiv_meta.db not found", "matches": []}

    clean_title = title.strip().strip('"').strip("'")
    if not clean_title:
        return {"status": "NOT_FOUND", "title": "", "matches": []}

    try:
        import sqlite3

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        tables = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        fts_table = "arxiv_fts" if "arxiv_fts" in tables else None
        fts_table = fts_table or ("papers_fts" if "papers_fts" in tables else None)
        content_table = "arxiv_meta" if "arxiv_meta" in tables else None
        content_table = content_table or ("papers" if "papers" in tables else None)

        if not fts_table or not content_table:
            conn.close()
            return {
                "status": "ERROR",
                "error": f"Expected FTS5+content tables not found. Tables: {list(tables)}",
                "matches": [],
            }

        fts_query = f'"{clean_title}"'
        cursor.execute(
            f"""
            SELECT c.arxiv_id, c.title, c.authors, c.published, c.abstract
            FROM {fts_table} f
            JOIN {content_table} c ON c.rowid = f.rowid
            WHERE {fts_table} MATCH ?
            ORDER BY rank
            LIMIT 5
        """,
            (fts_query,),
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return {"status": "NOT_FOUND", "title": title[:200], "matches": []}

        matches = []
        for row in rows:
            match = {
                "arxiv_id": row["arxiv_id"],
                "title": row["title"],
                "published": row["published"],
                "year": int(row["published"][:4]) if row["published"] else 0,
                "authors": row["authors"],
            }

            # Score using _text_similarity (from ARS)
            score = title_similarity(clean_title, row["title"] or "") * 0.8

            # Exact-match bonus
            if exact_match(clean_title, row["title"] or ""):
                score += 0.15

            # Year bonus (smaller to avoid over-weighting)
            if year_hint and match["year"]:
                if abs(match["year"] - year_hint) <= 1:
                    score += 0.2
                elif abs(match["year"] - year_hint) <= 3:
                    score += 0.1

            # Author bonus
            if authors_hint and row["authors"]:
                if authors_hint.lower() in row["authors"].lower():
                    score += 0.2

            match["score"] = round(min(score, 1.0), 2)
            matches.append(match)

        matches.sort(key=lambda m: m["score"], reverse=True)

        return {
            "status": _make_status(matches[0]["score"]),
            "title": title[:200],
            "matches": matches[:3],
        }

    except Exception as e:
        return {"status": "ERROR", "error": str(e), "matches": []}


def check_citation_by_arxiv_id(arxiv_id: str, db_path: Optional[str] = None) -> dict:
    """L1: Check if a paper exists by arXiv ID."""
    db = db_path or find_arxiv_db()
    if not db:
        return {"status": "ERROR", "error": "arxiv_meta.db not found"}

    try:
        import sqlite3

        conn = sqlite3.connect(db)
        cursor = conn.cursor()

        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        content_table = "arxiv_meta" if "arxiv_meta" in tables else None
        content_table = content_table or ("papers" if "papers" in tables else None)
        if not content_table:
            conn.close()
            return {"status": "ERROR", "error": f"No content table found. Tables: {tables}"}

        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT arxiv_id, title, authors, published FROM {content_table} WHERE arxiv_id = ?",
            (arxiv_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                "status": "VERIFIED",
                "arxiv_id": row["arxiv_id"],
                "title": row["title"],
                "year": int(row["published"][:4]) if row["published"] else 0,
                "authors": row["authors"],
            }
        return {"status": "NOT_FOUND", "arxiv_id": arxiv_id}

    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ─── L2/L3: External API Clients (lazy import) ──────


def _make_client_s2():
    """Lazy-import S2 client (avoids network overhead at import time)."""
    from hfpclawer.citation_audit_s2 import S2Client
    return S2Client()


def _make_client_oa():
    """Lazy-import OpenAlex client."""
    from hfpclawer.citation_audit_oa import OAClient
    return OAClient()


# ─── Orchestrator: check_citation ────────────────────

def check_citation(
    title: str,
    authors_hint: str = "",
    year_hint: int = 0,
    db_path: Optional[str] = None,
    source: CitationSource = "auto",
) -> dict:
    """Unified entry: chain L1 → L2 → L3 with fallback.

    Args:
        title: Paper title or key phrase.
        authors_hint: Optional author for disambiguation.
        year_hint: Optional publication year.
        db_path: L1 only — path to local arxiv_meta.db.
        source: "local", "s2", "openalex", or "auto" (default, L1→L2→L3).

    Returns:
        dict with keys: status, title, source, matches (per-source results).
    """
    results_by_source: dict[str, dict] = {}

    if source == "auto":
        sources_to_try: list[CitationSource] = ["local", "s2", "openalex"]
    else:
        sources_to_try = [source]

    for src in sources_to_try:
        try:
            if src == "local":
                result = check_citation_local(title, authors_hint, year_hint, db_path)
            elif src == "s2":
                client = _make_client_s2()
                result = client.lookup(title)
            elif src == "openalex":
                client = _make_client_oa()
                result = client.lookup(title)
            else:
                continue
        except Exception as e:
            result = {"status": "ERROR", "error": str(e), "matches": []}

        results_by_source[src] = result
        result["source"] = src

        # Early exit on VERIFIED or ERROR (auto mode)
        if source == "auto" and result.get("status") in ("VERIFIED", "ERROR"):
            break

    # Merge: use best status across sources
    merged = _merge_results(title, results_by_source)
    merged["per_source"] = results_by_source
    return merged


def _merge_results(title: str, results_by_source: dict[str, dict]) -> dict:
    """Merge per-source results into a single summary dict.

    Propagates detail fields (authors, year, doi, etc.) from the first
    VERIFIED source, or the first source with data.
    """
    statuses = [r.get("status", "NOT_FOUND") for r in results_by_source.values()]

    # Priority: VERIFIED > SUSPECTED > NOT_FOUND > ERROR
    if "VERIFIED" in statuses:
        status: CitationStatus = "VERIFIED"
    elif "SUSPECTED" in statuses:
        status = "SUSPECTED"
    elif any(s == "NOT_FOUND" for s in statuses):
        status = "NOT_FOUND"
    else:
        status = "ERROR"

    # Propagate detail fields from the best source
    merged = {"status": status, "title": title[:200]}
    detail_fields = ["authors", "year", "doi", "venue", "paper_id", "oa_id", "arxiv_id"]
    for r in results_by_source.values():
        if r.get("status") == "VERIFIED":
            for f in detail_fields:
                if f in r and r[f]:
                    merged[f] = r[f]
            break
    else:
        # No VERIFIED source — take from first non-ERROR source
        for r in results_by_source.values():
            if r.get("status") != "ERROR":
                for f in detail_fields:
                    if f in r and r[f]:
                        merged[f] = r[f]
                break

    return merged


# ─── Batched Audit ──────────────────────────────────


def extract_citations_from_text(text: str) -> list[dict]:
    """Parse simple citation patterns from text.

    Supports:
      - [Author, Year] "Title"
      - "Title" (Author et al., Year)
      - arXiv:XXXX.XXXXX
    """
    citations = []

    # arXiv IDs
    for m in ARXIV_ID_RE.finditer(text):
        citations.append({"type": "arxiv", "id": m.group(1), "source": m.group(0)})

    patterns = [
        r'"([^"]+)"\s*\(([A-Z][a-z]+(?:\s+(?:et\s+al\.?|&\s+[A-Z][a-z]+))?)\s*,?\s*(\d{4})\)',
        r'([A-Z][a-z]+(?:\s+(?:et\s+al\.?|&\s+[A-Z][a-z]+))?)\s*\((\d{4})\)\s*["\u201c]([^"\u201d]+)["\u201d]',
    ]
    for pat in patterns:
        for m in re.finditer(pat, text):
            groups = m.groups()
            if len(groups) >= 3:
                citations.append({
                    "type": "author-year-title",
                    "authors": groups[0].strip(),
                    "year": int(groups[1]),
                    "title": groups[2].strip(),
                    "source": m.group(0),
                })

    return citations


def batch_audit(
    texts: list[str],
    db_path: Optional[str] = None,
) -> list[dict]:
    """Run L1 check on a list of texts containing citations."""
    results: list[dict] = []
    for text in texts:
        citations = extract_citations_from_text(text)
        checks: list[dict] = []
        for cit in citations:
            if cit["type"] == "arxiv":
                result = check_citation_by_arxiv_id(cit["id"], db_path)
            elif cit["type"] == "author-year-title":
                result = check_citation(
                    cit.get("title", ""),
                    authors_hint=cit.get("authors", ""),
                    year_hint=cit.get("year", 0),
                    db_path=db_path,
                )
            else:
                result = {"status": "UNSUPPORTED"}
            result["citation"] = cit
            checks.append(result)
        results.append({"total_citations": len(citations), "checks": checks})
    return results


# ─── CLI ─────────────────────────────────────────────


def format_result(result: dict, indent: str = "") -> str:
    """Format a single citation check result for human reading."""
    status = result.get("status", "?")
    label = {
        "VERIFIED": "[OK]",
        "SUSPECTED": "[?]",
        "NOT_FOUND": "[NF]",
        "ERROR": "[ERR]",
    }.get(status, "[??]")
    lines = [f"{indent}{label} {status}"]
    if "arxiv_id" in result:
        lines.append(f"{indent}  arXiv: {result['arxiv_id']}")
    if "title" in result:
        lines.append(f"{indent}  Title: {result['title'][:100]}")
        lines.append(f"{indent}  Authors: {result.get('authors', 'N/A')}")
    if "matches" in result:
        for m in result["matches"][:2]:
            lines.append(
                f"{indent}  -> {m['arxiv_id']} ({m['score']:.2f}): {m['title'][:80]}"
            )
    if "error" in result:
        lines.append(f"{indent}  Error: {result['error']}")
    # Show per-source breakdown
    per_source = result.get("per_source", {})
    if per_source:
        src_parts = [f"{s}: {ps.get('status', '?')}" for s, ps in per_source.items()]
        lines.append(f"{indent}  Sources: {', '.join(src_parts)}")
    return "\n".join(lines)


def format_batch_report(results: list[dict]) -> str:
    """Format batch audit as readable report."""
    lines = []
    lines.append("=" * 50)
    lines.append("Citation Audit Report")
    lines.append(f"Time: {datetime.now().isoformat()}")
    lines.append(f"DB: {find_arxiv_db() or 'NOT FOUND'}")
    lines.append("=" * 50)
    lines.append("")

    total_verified = 0
    total_suspected = 0
    total_not_found = 0
    total_errors = 0
    total_citations = 0

    for r in results:
        total_citations += r.get("total_citations", 0)
        for c in r.get("checks", []):
            s = c.get("status", "")
            if s == "VERIFIED":
                total_verified += 1
            elif s == "SUSPECTED":
                total_suspected += 1
            elif s == "NOT_FOUND":
                total_not_found += 1
            elif s == "ERROR":
                total_errors += 1

        for c in r.get("checks", []):
            cit = c.get("citation", {})
            lines.append(f"Reference: {cit.get('source', 'N/A')}")
            lines.append(format_result(c, indent="  "))
            lines.append("")

    lines.append("-" * 40)
    lines.append(f"Total citations: {total_citations}")
    lines.append(f"  [OK] VERIFIED:   {total_verified}")
    lines.append(f"  [?]  SUSPECTED:  {total_suspected}")
    lines.append(f"  [NF] NOT_FOUND:  {total_not_found}")
    lines.append(f"  [ERR] ERROR:     {total_errors}")

    return "\n".join(lines)


def cli():
    """Simple CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="hfpclawer citation audit — L1 (local) → L2 (S2) → L3 (OpenAlex)"
    )
    parser.add_argument("--check", type=str, help="Check a single citation string")
    parser.add_argument("--arxiv-id", type=str, help="Check by arXiv ID")
    parser.add_argument("--refs", type=str, help="Check references from a text file")
    parser.add_argument("--batch", action="store_true", help="Run batch audit placeholder")
    parser.add_argument("--db", type=str, default=None, help="Path to arxiv_meta.db")
    parser.add_argument(
        "--source", type=str, default="auto",
        choices=["auto", "local", "s2", "openalex"],
        help="Citation source chain (default: auto = local→s2→openalex)",
    )
    args = parser.parse_args()

    if args.check:
        result = check_citation(args.check, db_path=args.db, source=args.source)
        print(format_result(result))

    elif args.arxiv_id:
        result = check_citation_by_arxiv_id(args.arxiv_id, db_path=args.db)
        print(format_result(result))

    elif args.refs:
        with open(args.refs) as f:
            text = f.read()
        citations = extract_citations_from_text(text)
        print(f"Found {len(citations)} citations in {args.refs}")
        for cit in citations:
            if cit["type"] == "arxiv":
                result = check_citation_by_arxiv_id(cit["id"], db_path=args.db)
            else:
                result = check_citation(
                    cit.get("title", ""),
                    authors_hint=cit.get("authors", ""),
                    year_hint=cit.get("year", 0),
                    db_path=args.db,
                )
            print(format_result(result))
            print()

    elif args.batch:
        print(format_batch_report([]))
        print("\n\u26a0\ufe0f Batch audit: pass --refs or implement paper_store scanning")

    else:
        parser.print_help()


if __name__ == "__main__":
    cli()
