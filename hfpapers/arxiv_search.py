#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ─── Local arXiv Metadata Search Engine ──────────────
# hfpapers/arxiv_search.py
# Local FTS5 search engine built from Kaggle arXiv full metadata (2.69M papers)
# Fallback for arXiv API — zero network dependency, millisecond response
# Supports cross-database validation (bidirectional DOI ↔ CrossRef with paper_store)

import json
import logging
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from hfpapers.config import get as cfg_get

logger = logging.getLogger("hfpapers.arxiv_search")

# FTS5 full-text index + metadata table
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS arxiv_fts USING fts5(
    arxiv_id UNINDEXED,
    title,
    authors,
    abstract,
    categories UNINDEXED,
    doi UNINDEXED,
    journal_ref UNINDEXED,
    update_date UNINDEXED,
    tokenize='porter unicode61'
);
"""

META_SCHEMA = """
CREATE TABLE IF NOT EXISTS arxiv_meta (
    arxiv_id TEXT PRIMARY KEY,
    title TEXT,
    authors TEXT,
    abstract TEXT,
    categories TEXT,
    doi TEXT,
    journal_ref TEXT,
    update_date TEXT,
    imported_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_arxiv_meta_date ON arxiv_meta(update_date);
CREATE INDEX IF NOT EXISTS idx_arxiv_meta_cat ON arxiv_meta(categories);
CREATE INDEX IF NOT EXISTS idx_arxiv_meta_doi ON arxiv_meta(doi);
"""


class ArxivLocalSearch:
    """Local arXiv Metadata FTS5 Engine

    Standalone deployment, no network needed, millisecond search across 2.69M papers.
    Supports cross-database DOI cross-validation (integrated with paper_store CrossrefClient).

    Usage:
        engine = ArxivLocalSearch()
        results = engine.search("neural operator", limit=50, year_from=2017)
        paper = engine.get_by_id("2010.08895")
    """

    DOI_RE = re.compile(r"10\.\d{4,}/[^\s]+")

    def __init__(self, db_path: str = None):
        if db_path is None:
            base = Path(__file__).parent.parent
            db_path = str(base / cfg_get("paths.data_dir", "data") / "arxiv_meta.db")
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA cache_size=-80000")  # 80 MB cache
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(FTS_SCHEMA)
            conn.executescript(META_SCHEMA)
        logger.debug(f"ArxivLocalSearch ready: {self.db_path}")

    def search(
        self,
        query: str,
        limit: int = 50,
        year_from: int = 0,
        year_to: int = 0,
        categories: list[str] = None,
        sort: str = "relevance",
    ) -> list[dict]:
        """Full-text search arXiv metadata

        Args:
            query: FTS5 query syntax
            limit: Maximum number of results
            year_from: Start year
            year_to: End year, 0=unlimited
            categories: Category filter (e.g. ["cs.LG", "math.NA"])
            sort: "relevance" | "date"

        Returns:
            [{"arxiv_id", "title", "authors", "abstract", "categories",
              "doi", "journal_ref", "update_date", "score"}, ...]
        """
        with self._lock, self._conn() as conn:
            if sort == "date":
                # Filter by year then sort by date (needs JOIN meta)
                sql = """SELECT f.arxiv_id, m.title, m.authors, m.abstract, m.categories,
                                m.doi, m.journal_ref, m.update_date, rank
                         FROM arxiv_fts f
                         JOIN arxiv_meta m ON f.arxiv_id = m.arxiv_id
                         WHERE arxiv_fts MATCH ?
                         ORDER BY m.update_date DESC
                         LIMIT ?"""
            else:
                sql = """SELECT arxiv_id, title, authors, abstract, categories,
                                doi, journal_ref, update_date, rank
                         FROM arxiv_fts
                         WHERE arxiv_fts MATCH ?
                         ORDER BY rank
                         LIMIT ?"""
            rows = conn.execute(sql, (query, limit * 3)).fetchall()

        results = []
        for r in rows:
            r = dict(r)
            update = r.get("update_date") or ""
            year_str = update[:4]

            # Year filter
            if year_from and year_str:
                try:
                    if int(year_str) < year_from:
                        continue
                except ValueError:
                    pass
            if year_to and year_str:
                try:
                    if int(year_str) > year_to:
                        continue
                except ValueError:
                    pass

            # Category filter
            if categories:
                cats = (r.get("categories") or "").split()
                if not any(c in cats for c in categories):
                    continue

            results.append(
                {
                    "arxiv_id": r["arxiv_id"],
                    "title": r["title"] or "",
                    "authors": r["authors"] or "",
                    "abstract": r["abstract"] or "",
                    "categories": (r["categories"] or "").split(),
                    "doi": r["doi"] or "",
                    "journal_ref": r["journal_ref"] or "",
                    "update_date": update,
                    "score": -r["rank"] if r["rank"] else 0,
                }
            )
            if len(results) >= limit:
                break

        return results

    def get_by_id(self, arxiv_id: str) -> Optional[dict]:
        """Lookup a single paper by arXiv ID"""
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM arxiv_meta WHERE arxiv_id = ?", (arxiv_id,)).fetchone()
        if r:
            return dict(r)
        return None

    def get_by_dois(self, dois: list[str]) -> list[dict]:
        """Batch lookup by DOI"""
        if not dois:
            return []
        placeholders = ",".join("?" for _ in dois)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM arxiv_meta WHERE doi IN ({placeholders})", dois
            ).fetchall()
        return [dict(r) for r in rows]

    def cross_validate(self, paper_store_doi: str) -> Optional[dict]:
        """Reverse-validate arXiv ID from paper_store DOI

        When a paper in paper_store has a DOI but no arXiv ID,
        use ArxivLocalSearch's DOI index to look up the arXiv ID.
        """
        with self._conn() as conn:
            r = conn.execute(
                "SELECT arxiv_id, title, authors, categories FROM arxiv_meta WHERE doi = ?",
                (paper_store_doi,),
            ).fetchone()
        if r:
            return dict(r)
        return None

    def stats(self) -> dict:
        """Database statistics"""
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM arxiv_meta").fetchone()[0]
            has_doi = conn.execute("SELECT COUNT(*) FROM arxiv_meta WHERE doi != ''").fetchone()[0]
            has_journal = conn.execute(
                "SELECT COUNT(*) FROM arxiv_meta WHERE journal_ref != ''"
            ).fetchone()[0]
            years = conn.execute(
                "SELECT substr(update_date,1,4) as y, COUNT(*) as c "
                "FROM arxiv_meta GROUP BY y ORDER BY y DESC"
            ).fetchall()
            # DOI coverage
            doi_with_journal = conn.execute(
                "SELECT COUNT(*) FROM arxiv_meta WHERE doi != '' AND journal_ref != ''"
            ).fetchone()[0]
        return {
            "total": total,
            "with_doi": has_doi,
            "with_journal": has_journal,
            "doi_with_journal": doi_with_journal,
            "years": {r[0]: r[1] for r in years},
        }

    def import_json_lines(self, jsonl_path: str, batch_size: int = 2000):
        """Batch import from Kaggle JSON Lines file

        Format: One JSON per line
        {"id": "0704.0001", "title": "...", "authors": "...",
         "abstract": "...", "categories": "cs.LG math.NA",
         "doi": "10.xxx/yyy", "journal_ref": "NeurIPS 2023",
         "update_date": "2023-12-01"}
        """
        total = 0
        batch = []
        start = time.time()

        with open(jsonl_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    paper = json.loads(line)
                    arxiv_id = paper.get("id", "")
                    if not arxiv_id:
                        continue
                    batch.append(
                        (
                            arxiv_id,
                            paper.get("title", "")[:500],
                            paper.get("authors", "")[:500],
                            paper.get("abstract", "")[:2000],
                            paper.get("categories", ""),
                            paper.get("doi", ""),
                            paper.get("journal_ref", "")[:200],
                            paper.get("update_date", ""),
                        )
                    )
                    total += 1
                except json.JSONDecodeError:
                    continue

                if len(batch) >= batch_size:
                    self._import_batch(batch)
                    batch = []
                    elapsed = time.time() - start
                    rate = total / elapsed if elapsed > 0 else 0
                    if total % 50000 == 0:
                        logger.info(f"Imported {total:,} papers ({rate:.0f}/s)...")

        if batch:
            self._import_batch(batch)

        elapsed = time.time() - start
        logger.info(
            f"Import complete: {total:,} papers in {elapsed:.1f}s ({total / elapsed:.0f}/s)"
        )
        return total

    def _import_batch(self, batch: list[tuple]):
        """Write a batch to SQLite + FTS5"""
        with self._lock, self._conn() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO arxiv_meta
                   (arxiv_id, title, authors, abstract, categories,
                    doi, journal_ref, update_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                batch,
            )
            conn.executemany(
                """INSERT OR IGNORE INTO arxiv_fts
                   (arxiv_id, title, authors, abstract, categories,
                    doi, journal_ref, update_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                batch,
            )
            conn.commit()

    def count(self) -> int:
        """Total paper count"""
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM arxiv_meta").fetchone()[0]

    def __repr__(self):
        return f"<ArxivLocalSearch {self.db_path} count={self.count()}>"


# ─── Scrapy Integration: arXiv Local Spider ──────────
# No network requests — search directly from local FTS5 index


class ArxivLocalSpider:
    """Local arXiv Search Spider (outputs unified SourcePaper)

    No network required, millisecond response. Replaces ArxivApiSource and HfCliSource fallback.
    Particularly suitable for large-scale batch search (1000+ queries).
    """

    name = "arxiv_local"

    def __init__(self, engine: ArxivLocalSearch = None):
        self.engine = engine or ArxivLocalSearch()

    def search(
        self, query: str, limit: int = 100, year_from: int = 2017, categories: list[str] = None
    ) -> list[dict]:
        """Search and return format compatible with hfpapers.sources.SourcePaper"""
        results = self.engine.search(
            query=query,
            limit=limit,
            year_from=year_from,
            categories=categories,
            sort="date",
        )
        # Convert to unified format
        papers = []
        for r in results:
            doi = r.get("doi", "")
            journal_ref = r.get("journal_ref", "")
            papers.append(
                {
                    "arxiv_id": r["arxiv_id"],
                    "title": r["title"],
                    "abstract": r["abstract"],
                    "source": "arxiv_local",
                    "source_url": f"https://arxiv.org/abs/{r['arxiv_id']}",
                    "categories": r.get("categories", []),
                    "doi": doi,
                    "venue": journal_ref,
                    "authors": r.get("authors", ""),
                    "published_date": r.get("update_date", ""),
                    # Academic confidence: DOI + venue → high confidence
                    "confidence": 0.9 if doi and journal_ref else (0.6 if doi else 0.3),
                }
            )
        return papers
