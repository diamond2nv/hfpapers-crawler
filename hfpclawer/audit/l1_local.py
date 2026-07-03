#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l1_local.py — L1: Local SQLite existence check (arxiv_meta.db FTS5).

Migrated from hfpclawer.citation_audit (CC BY-NC 4.0, Cheng-I Wu).
"""

import logging
import os
import re
from typing import Optional

from hfpclawer.audit.similarity import exact_match, normalize_title, title_similarity

logger = logging.getLogger("hfpclawer.audit.l1_local")

DEFAULT_DB_PATHS = [
    os.path.expanduser("~/Gitlab/Agentic4Sci/arxiv-metadata-service/data/arxiv_meta.db"),
    "data/arxiv_meta.db",
]

ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")
TITLE_SIMILARITY_THRESHOLD = 0.70


def find_arxiv_db() -> Optional[str]:
    """Find the local arxiv_meta.db (returns first existing path)."""
    for p in DEFAULT_DB_PATHS:
        if os.path.exists(p):
            return p
    return None


def _make_status(score: float) -> str:
    """Convert a score [0,1] to a status label."""
    if score >= TITLE_SIMILARITY_THRESHOLD:
        return "VERIFIED"
    elif score >= 0.40:
        return "SUSPECTED"
    else:
        return "NOT_FOUND"


def check_citation_local(
    title: str,
    authors_hint: str = "",
    year_hint: int = 0,
    arxiv_id: str = "",
    db_path: Optional[str] = None,
) -> dict:
    """L1: Check if a cited paper exists in local arxiv_meta.db FTS5.

    Supports both title-based and arXiv ID-based lookup.
    Returns dict with: status, title, matches (sorted by score).
    """
    # Prefer arXiv ID lookup
    if arxiv_id:
        clean = ARXIV_ID_RE.sub(r"\1", arxiv_id.strip())
        return _lookup_by_arxiv_id(clean, db_path)

    # Title-based FTS5 search
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

        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        fts_table = "arxiv_fts" if "arxiv_fts" in tables else None
        fts_table = fts_table or ("papers_fts" if "papers_fts" in tables else None)
        content_table = "arxiv_meta" if "arxiv_meta" in tables else None
        content_table = content_table or ("papers" if "papers" in tables else None)

        if not fts_table or not content_table:
            conn.close()
            return {"status": "ERROR",
                    "error": f"Expected FTS5 tables not found. Tables: {list(tables)}",
                    "matches": []}

        fts_query = f'"{clean_title}"'
        cursor.execute(
            f"""SELECT c.arxiv_id, c.title, c.authors, c.published, c.abstract
                FROM {fts_table} f
                JOIN {content_table} c ON c.rowid = f.rowid
                WHERE {fts_table} MATCH ?
                ORDER BY rank LIMIT 5""",
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
            score = title_similarity(clean_title, row["title"] or "") * 0.8
            if exact_match(clean_title, row["title"] or ""):
                score += 0.15
            if year_hint and match["year"]:
                diff = abs(match["year"] - year_hint)
                if diff <= 1:
                    score += 0.2
                elif diff <= 3:
                    score += 0.1
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
        logger.warning("L1 local lookup error: %s", e)
        return {"status": "ERROR", "error": str(e), "matches": []}


def _lookup_by_arxiv_id(arxiv_id: str, db_path: Optional[str] = None) -> dict:
    """Look up a paper by arXiv ID in the local DB."""
    db = db_path or find_arxiv_db()
    if not db:
        return {"status": "ERROR", "error": "arxiv_meta.db not found", "matches": []}

    try:
        import sqlite3
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT arxiv_id, title, authors, published, abstract FROM arxiv_meta WHERE arxiv_id = ?",
            (arxiv_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return {"status": "NOT_FOUND", "arxiv_id": arxiv_id, "matches": []}
        return {
            "status": "VERIFIED",
            "arxiv_id": row["arxiv_id"],
            "title": row["title"],
            "matches": [dict(row)],
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "matches": []}
