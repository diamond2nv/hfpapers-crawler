#!/usr/bin/env python3
"""
paper_store.py — Unified Paper Storage Engine

Features:
  - Snowflake ID Generator (Snowflake ID, 64-bit)
  - SQLite unified storage: papers main table + identifiers mapping table
  - Multi-identifier cross-validation: arXiv ID ↔ DOI ↔ OpenReview Forum ↔ ISSN ↔ PNS
  - Crossref API lookup: title→DOI, DOI→arXiv (eprint)

Architecture:
                   ┌──────────────────┐
                   │   paper_store    │
                   ├──────────────────┤
                   │ Snowflake ID gen │
                   │ SQLite (3 tables)│
                   │ Crossref client  │
                   └────────┬─────────┘
                            │
          ┌─────────────────┼──────────────────┐
          ▼                 ▼                   ▼
   pipeline.py        evolved.py          sources.py
   (Scrapy)           (CLI crawler)       (multi-source search)

State management:
  - Dedup file ~/wiki/raw/papers/hfpapers-crawled.json still maintained
  - SQLite as authoritative source, JSON as fast query cache
  - Dual-write during migration
"""

import json
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

from hfpapers.config import get as cfg_get

logger = logging.getLogger("hfpapers.paper_store")

# ─── Constants ──────────────────────────────────
ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")
DOI_RE = re.compile(r"10\.\d{4,}/[^\s]+")

# ─── Snowflake ID generator (yitter snowflake drift algorithm)────
# Source: https://github.com/yitter/IdGenerator
# Optimized snowflake algorithm — supports time rollback, shorter IDs, higher performance
# Thread-safe, 500K/0.1s concurrency on single machine
#
# External interface (backward compatible):
#   snowflake_id(worker_id=None) -> int
#   snowflake_timestamp(sf_id) -> datetime
#   init_snowflake_worker(worker_id)  — Initialize WorkerId
#
# WorkerId configuration priority:
#   1. Explicit call to init_snowflake_worker()
#   2. _TEST_SNOWFLAKE_WORKER Environment variable
#   3. Config file snowflake.worker_id
#   4. PID hash to 0-63 (fallback)

_SNOWFLAKE_LOCK = threading.Lock()
_SNOWFLAKE_GEN: Optional["_SnowflakeM1"] = None
_SNOWFLAKE_WORKER_ID: int = 0
_SNOWFLAKE_BASE_TIME: int = 1728000000000  # 2024-10-04


class _IdGeneratorOptions:
    """Snowflake drift algorithm configuration options"""

    def __init__(self, worker_id: int = 0):
        self.method: int = 1  # 1=Drift algorithm
        self.base_time: int = _SNOWFLAKE_BASE_TIME
        self.worker_id: int = worker_id
        self.worker_id_bit_length: int = 6  # [1,15] WorkerId range 0-63
        self.seq_bit_length: int = 6  # [3,21] 64 base IDs per millisecond
        self.max_seq_number: int = 0  # 0=auto (2^seq_bit_length-1)
        self.min_seq_number: int = 5  # First 5 reserved bits (rollback reserve)
        self.top_over_cost_count: int = 2000  # Max drift count


class _SnowflakeM1:
    """Snowflake drift algorithm M1 implementation"""

    def __init__(self, options: _IdGeneratorOptions):
        self.base_time = int(options.base_time)
        self.worker_id_bit_length = int(options.worker_id_bit_length)
        self.worker_id = int(options.worker_id)
        self.seq_bit_length = int(options.seq_bit_length)
        self.max_seq_number = int(options.max_seq_number)
        if options.max_seq_number <= 0:
            self.max_seq_number = (1 << self.seq_bit_length) - 1
        self.min_seq_number = int(options.min_seq_number)
        self.top_over_cost_count = int(options.top_over_cost_count)

        self._timestamp_shift = self.worker_id_bit_length + self.seq_bit_length
        self._current_seq_number = self.min_seq_number
        self._last_time_tick: int = 0
        self._turn_back_time_tick: int = 0
        self._turn_back_index: int = 0
        self._is_over_cost = False
        self._over_cost_count = 0
        self._lock = threading.Lock()

    def _get_current_time_tick(self) -> int:
        return int((time.time_ns() / 1e6) - self.base_time)

    def _get_next_time_tick(self) -> int:
        tick = self._get_current_time_tick()
        while tick <= self._last_time_tick:
            time.sleep(0.001)
            tick = self._get_current_time_tick()
        return tick

    def _calc_id(self, use_time_tick: int) -> int:
        self._current_seq_number += 1
        return (
            (use_time_tick << self._timestamp_shift)
            + (self.worker_id << self.seq_bit_length)
            + self._current_seq_number
        )

    def _calc_turn_back_id(self, use_time_tick: int) -> int:
        self._turn_back_time_tick -= 1
        return (
            (use_time_tick << self._timestamp_shift)
            + (self.worker_id << self.seq_bit_length)
            + self._turn_back_index
        )

    def _next_over_cost_id(self) -> int:
        current = self._get_current_time_tick()
        if current > self._last_time_tick:
            self._last_time_tick = current
            self._current_seq_number = self.min_seq_number
            self._is_over_cost = False
            self._over_cost_count = 0
            return self._calc_id(self._last_time_tick)

        if self._over_cost_count >= self.top_over_cost_count:
            self._last_time_tick = self._get_next_time_tick()
            self._current_seq_number = self.min_seq_number
            self._is_over_cost = False
            self._over_cost_count = 0
            return self._calc_id(self._last_time_tick)

        if self._current_seq_number > self.max_seq_number:
            self._last_time_tick += 1
            self._current_seq_number = self.min_seq_number
            self._is_over_cost = True
            self._over_cost_count += 1
            return self._calc_id(self._last_time_tick)

        return self._calc_id(self._last_time_tick)

    def _next_normal_id(self) -> int:
        current = self._get_current_time_tick()
        if current < self._last_time_tick:
            # Time rollback handling
            if self._turn_back_time_tick < 1:
                self._turn_back_time_tick = self._last_time_tick - 1
                self._turn_back_index += 1
                if self._turn_back_index > 4:
                    self._turn_back_index = 1
            return self._calc_turn_back_id(self._turn_back_time_tick)

        self._turn_back_time_tick = min(self._turn_back_time_tick, 0)

        if current > self._last_time_tick:
            self._last_time_tick = current
            self._current_seq_number = self.min_seq_number
            return self._calc_id(self._last_time_tick)

        if self._current_seq_number > self.max_seq_number:
            self._last_time_tick += 1
            self._current_seq_number = self.min_seq_number
            self._is_over_cost = True
            self._over_cost_count = 1
            return self._calc_id(self._last_time_tick)

        return self._calc_id(self._last_time_tick)

    def next_id(self) -> int:
        with self._lock:
            if self._is_over_cost:
                return self._next_over_cost_id()
            return self._next_normal_id()


def _resolve_worker_id() -> int:
    """Determine WorkerId value"""
    # 1. Environment variable
    env_wid = os.environ.get("_TEST_SNOWFLAKE_WORKER")
    if env_wid:
        return int(env_wid)
    # 2. Config file
    try:
        cfg_wid = cfg_get("snowflake.worker_id", 0)
        if cfg_wid:
            return int(cfg_wid)
    except Exception:
        pass
    # 3. fallback: PID hash to 0-63
    pid = os.getpid()
    return (pid * 2654435761) & 0x3F  # Knuth multiplicative hash


def _get_snowflake() -> _SnowflakeM1:
    """Get/initialize snowflake generator singleton"""
    global _SNOWFLAKE_GEN, _SNOWFLAKE_WORKER_ID
    if _SNOWFLAKE_GEN is not None:
        return _SNOWFLAKE_GEN
    with _SNOWFLAKE_LOCK:
        if _SNOWFLAKE_GEN is not None:
            return _SNOWFLAKE_GEN
        wid = _resolve_worker_id()
        _SNOWFLAKE_WORKER_ID = wid
        opts = _IdGeneratorOptions(worker_id=wid)
        _SNOWFLAKE_GEN = _SnowflakeM1(opts)
        logger.info(f"Snowflake initialized: worker_id={wid}")
        return _SNOWFLAKE_GEN


def init_snowflake_worker(worker_id: int):
    """Explicitly initialize WorkerId (for distributed deployment)"""
    global _SNOWFLAKE_GEN, _SNOWFLAKE_WORKER_ID
    with _SNOWFLAKE_LOCK:
        _SNOWFLAKE_WORKER_ID = worker_id
        opts = _IdGeneratorOptions(worker_id=worker_id)
        _SNOWFLAKE_GEN = _SnowflakeM1(opts)
        logger.info(f"Snowflake re-initialized: worker_id={worker_id}")


def snowflake_id(worker_id: int = None) -> int:
    """Generate snowflake ID (backward compatible interface)

    If worker_id is passed, it will override globally in the current thread,
    but does not affect the global generator. The global generator uses auto-resolved worker_id.
    """
    if worker_id is not None:
        # Temporarily generate with specified worker_id (for testing)
        opts = _IdGeneratorOptions(worker_id=worker_id)
        gen = _SnowflakeM1(opts)
        return gen.next_id()
    return _get_snowflake().next_id()


def snowflake_timestamp(sf_id: int) -> datetime:
    """Extract timestamp from snowflake ID (backward compatible interface)

    Note: yitter ID bit layout:
      ID = (time_tick << shift) + (worker_id << seq_bit) + seq
    Where time_tick = current ms - base_time
    Therefore time_tick = sf_id >> shift (when seq and worker don't exceed bit width)
    """
    shift = 12  # default 6+6
    try:
        if _SNOWFLAKE_GEN:
            shift = _SNOWFLAKE_GEN._timestamp_shift
    except Exception:
        pass
    time_tick = sf_id >> shift
    ms = time_tick + _SNOWFLAKE_BASE_TIME
    return datetime.fromtimestamp(ms / 1000.0)


# ─── Data Model ───────────────────────────────


@dataclass
class PaperRecord:
    """Paper main record"""

    sf_id: int = 0  # Snowflake ID
    title: str = ""
    abstract: str = ""
    year: int = 0
    source: str = ""  # First discovered source
    venue: str = ""  # Venue full name
    relevance: int = 0  # Relevance 0-100
    has_code: bool = False
    code_url: str = ""
    verified: bool = False  # Cross-verified
    created_at: str = ""
    updated_at: str = ""


@dataclass
class PaperIdentifier:
    """Paper identifier mapping (N:1 → PaperRecord)"""

    sf_id: int  # Associated paper snowflake ID
    id_type: str  # "arxiv" / "doi" / "openreview" / "issn" / "pns" / "isbn"
    id_value: str  # Identifier value
    source: str = ""  # Source of this ID
    confidence: float = 1.0  # Confidence 0-1
    verified_at: str = ""  # Verification time


# ─── SQLite Storage Layer ──────────────────────────


def _db_path() -> str:
    """Database file path"""
    base = cfg_get("paths.data_dir", "data")
    # If base is a relative path, resolve relative to current working directory
    if not os.path.isabs(base):
        base = os.path.join(os.getcwd(), base)
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "papers.db")


class PaperStore:
    """Paper storage engine — SQLite backend"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or _db_path()
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        """Initialize table schema"""
        with self._lock, self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS papers (
                    sf_id       INTEGER PRIMARY KEY,  -- Snowflake ID
                    title       TEXT NOT NULL DEFAULT '',
                    abstract    TEXT DEFAULT '',
                    year        INTEGER DEFAULT 0,
                    source      TEXT DEFAULT '',       -- First source
                    venue       TEXT DEFAULT '',       -- Venue
                    relevance   INTEGER DEFAULT 0,     -- Relevance 0-100
                    has_code    INTEGER DEFAULT 0,     -- Has code
                    code_url    TEXT DEFAULT '',
                    verified    INTEGER DEFAULT 0,     -- Cross-verified
                    created_at  TEXT DEFAULT (datetime('now')),
                    updated_at  TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS identifiers (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    sf_id       INTEGER NOT NULL,       -- Associated paper
                    id_type     TEXT NOT NULL,            -- arxiv/doi/openreview/issn/pns
                    id_value    TEXT NOT NULL,            -- Identifier value
                    source      TEXT DEFAULT '',          -- Source of this ID
                    confidence  REAL DEFAULT 1.0,         -- Confidence
                    verified_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(id_type, id_value),
                    FOREIGN KEY (sf_id) REFERENCES papers(sf_id)
                );

                CREATE TABLE IF NOT EXISTS crossref_cache (
                    doi         TEXT PRIMARY KEY,
                    title       TEXT DEFAULT '',
                    arxiv_id    TEXT DEFAULT '',        -- Extracted from BibTeX eprint
                    venue       TEXT DEFAULT '',
                    authors     TEXT DEFAULT '',        -- JSON array
                    year        INTEGER DEFAULT 0,
                    raw_json    TEXT DEFAULT '',        -- Raw response summary
                    queried_at  TEXT DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_identifiers_sf_id
                    ON identifiers(sf_id);
                CREATE INDEX IF NOT EXISTS idx_identifiers_type_value
                    ON identifiers(id_type, id_value);
                CREATE INDEX IF NOT EXISTS idx_papers_relevance
                    ON papers(relevance DESC);
                CREATE INDEX IF NOT EXISTS idx_papers_created
                    ON papers(created_at DESC);
            """)

    # ─── Paper CRUD ───────────────────────────

    def upsert_paper(self, record: PaperRecord) -> int:
        """Write or update paper. Returns sf_id."""
        with self._lock, self._conn() as conn:
            if record.sf_id:
                # Update
                conn.execute(
                    """
                    UPDATE papers SET
                        title=?, abstract=?, year=?, source=?,
                        venue=?, relevance=?, has_code=?, code_url=?,
                        verified=?, updated_at=datetime('now')
                    WHERE sf_id=?
                """,
                    (
                        record.title,
                        record.abstract,
                        record.year,
                        record.source,
                        record.venue,
                        record.relevance,
                        int(record.has_code),
                        record.code_url,
                        int(record.verified),
                        record.sf_id,
                    ),
                )
            else:
                # Insert
                sf_id = snowflake_id()
                record.sf_id = sf_id
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    """
                    INSERT INTO papers
                        (sf_id, title, abstract, year, source, venue,
                         relevance, has_code, code_url, verified,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        sf_id,
                        record.title,
                        record.abstract,
                        record.year,
                        record.source,
                        record.venue,
                        record.relevance,
                        int(record.has_code),
                        record.code_url,
                        int(record.verified),
                        now,
                        now,
                    ),
                )
                record.created_at = now
                record.updated_at = now
            return record.sf_id

    def get_paper_by_id(self, sf_id: int) -> Optional[PaperRecord]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM papers WHERE sf_id=?", (sf_id,)).fetchone()
            if row:
                return self._row_to_record(row)
            return None

    def get_paper_by_identifier(self, id_type: str, id_value: str) -> Optional[PaperRecord]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT p.* FROM papers p
                JOIN identifiers i ON p.sf_id = i.sf_id
                WHERE i.id_type=? AND i.id_value=?
            """,
                (id_type, id_value),
            ).fetchone()
            if row:
                return self._row_to_record(row)
            return None

    def get_all_papers(self) -> list[PaperRecord]:
        """Get all papers, ordered by creation time descending"""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM papers
                ORDER BY created_at DESC
            """).fetchall()
            return [self._row_to_record(r) for r in rows]

    def export_papers(self, format: str = "json", filepath: str = None) -> str:
        """Export all papers to file.

        Args:
            format: "json" or "csv"
            filepath: Output path, None for auto-naming

        Returns:
            Absolute path to output file
        """
        papers = self.get_all_papers()
        if not papers:
            raise ValueError("PaperStore has no papers to export")

        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(
                os.path.dirname(self.db_path), f"papers_export_{timestamp}.{format}"
            )

        if format == "json":
            data = []
            for p in papers:
                ids = self.get_identifiers(p.sf_id)
                data.append(
                    {
                        "sf_id": p.sf_id,
                        "title": p.title,
                        "abstract": p.abstract[:500] if p.abstract else "",
                        "year": p.year,
                        "source": p.source,
                        "venue": p.venue,
                        "relevance": p.relevance,
                        "has_code": p.has_code,
                        "code_url": p.code_url,
                        "verified": p.verified,
                        "created_at": p.created_at,
                        "updated_at": p.updated_at,
                        "identifiers": [
                            {"type": i.id_type, "value": i.id_value, "confidence": i.confidence}
                            for i in ids
                        ],
                    }
                )
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        elif format == "csv":
            import csv

            with open(filepath, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "sf_id",
                        "title",
                        "abstract_preview",
                        "year",
                        "source",
                        "venue",
                        "relevance",
                        "has_code",
                        "code_url",
                        "verified",
                        "created_at",
                        "updated_at",
                        "identifiers",
                    ]
                )
                for p in papers:
                    ids = self.get_identifiers(p.sf_id)
                    id_str = "; ".join(f"{i.id_type}:{i.id_value}" for i in ids)
                    writer.writerow(
                        [
                            p.sf_id,
                            p.title,
                            (p.abstract or "")[:500],
                            p.year,
                            p.source,
                            p.venue,
                            p.relevance,
                            int(p.has_code),
                            p.code_url,
                            int(p.verified),
                            p.created_at,
                            p.updated_at,
                            id_str,
                        ]
                    )
        else:
            raise ValueError(f"Unsupported format: {format}, only json/csv supported")

        logger.info(f"Exported {len(papers)} papers to {filepath}")
        return os.path.abspath(filepath)

    def search_papers(self, keyword: str = "", limit: int = 50) -> list[PaperRecord]:
        with self._conn() as conn:
            if keyword:
                rows = conn.execute(
                    """
                    SELECT * FROM papers
                    WHERE title LIKE ? OR abstract LIKE ?
                    ORDER BY relevance DESC, created_at DESC
                    LIMIT ?
                """,
                    (f"%{keyword}%", f"%{keyword}%", limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM papers
                    ORDER BY relevance DESC, created_at DESC
                    LIMIT ?
                """,
                    (limit,),
                ).fetchall()
            return [self._row_to_record(r) for r in rows]

    def update_paper(self, sf_id: int, **kwargs) -> bool:
        """Update specific fields of a paper (relevance/code_url/venue)"""
        allowed = {"relevance", "code_url", "venue", "has_code", "year", "abstract", "source"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values())
        vals.append(sf_id)
        try:
            with self._lock, self._conn() as conn:
                conn.execute(
                    f"UPDATE papers SET {sets}, updated_at=datetime('now') WHERE sf_id=?",
                    vals,
                )
            return True
        except Exception as e:
            logger.warning(f"update_paper failed: {e}")
            return False

    def stats(self) -> dict:
        """Statistics (same as store_stats())"""
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
            verified = conn.execute("SELECT COUNT(*) FROM papers WHERE verified=1").fetchone()[0]
            with_code = conn.execute("SELECT COUNT(*) FROM papers WHERE has_code=1").fetchone()[0]
            id_count = conn.execute("SELECT COUNT(*) FROM identifiers").fetchone()[0]
            id_types = conn.execute(
                "SELECT id_type, COUNT(*) FROM identifiers GROUP BY id_type"
            ).fetchall()
            return {
                "papers_total": total,
                "papers_verified": verified,
                "papers_with_code": with_code,
                "identifiers_total": id_count,
                "identifiers_by_type": dict(id_types),
            }

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> PaperRecord:
        return PaperRecord(
            sf_id=row["sf_id"],
            title=row["title"],
            abstract=row["abstract"],
            year=row["year"],
            source=row["source"],
            venue=row["venue"],
            relevance=row["relevance"],
            has_code=bool(row["has_code"]),
            code_url=row["code_url"],
            verified=bool(row["verified"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ─── Identifier Management ──────────────────────────

    def add_identifier(
        self, sf_id: int, id_type: str, id_value: str, source: str = "", confidence: float = 1.0
    ) -> bool:
        """Add an identifier mapping to a paper. Skip if exists."""
        try:
            with self._lock, self._conn() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO identifiers
                        (sf_id, id_type, id_value, source, confidence)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (sf_id, id_type, id_value, source, confidence),
                )
                return True
        except Exception as e:
            logger.warning(f"add_identifier failed: {e}")
            return False

    def get_identifiers(self, sf_id: int) -> list[PaperIdentifier]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM identifiers WHERE sf_id=?", (sf_id,)).fetchall()
            return [
                PaperIdentifier(
                    sf_id=r["sf_id"],
                    id_type=r["id_type"],
                    id_value=r["id_value"],
                    source=r["source"],
                    confidence=r["confidence"],
                    verified_at=r["verified_at"],
                )
                for r in rows
            ]

    def find_paper_by_any_id(self, id_value: str) -> Optional[PaperRecord]:
        """Find paper by any identifier value (auto-detect type)"""
        # Try direct match first
        for id_type in ("arxiv", "doi", "openreview", "issn", "pns", "isbn"):
            paper = self.get_paper_by_identifier(id_type, id_value)
            if paper:
                return paper

        # Try ARXIV_ID_RE match
        m = ARXIV_ID_RE.search(id_value)
        if m:
            paper = self.get_paper_by_identifier("arxiv", m.group(1))
            if paper:
                return paper

        # Try DOI_RE match
        m = DOI_RE.search(id_value)
        if m:
            paper = self.get_paper_by_identifier("doi", m.group(0))
            if paper:
                return paper

        return None

    # ─── Cross validation ────────────────────────────

    def verify_paper(self, sf_id: int) -> bool:
        """Check if paper has ≥2 identifiers from different sources, mark as verified"""
        ids = self.get_identifiers(sf_id)
        types = set(i.id_type for i in ids)
        if len(types) >= 2:
            with self._lock, self._conn() as conn:
                conn.execute(
                    "UPDATE papers SET verified=1, updated_at=datetime('now') WHERE sf_id=?",
                    (sf_id,),
                )
            return True
        return False


# ─── Crossref Client ─────────────────────────


class CrossrefClient:
    """Crossref API client — DOI query + cross validation"""

    BASE = "https://api.crossref.org"

    def __init__(self, mailto: str = ""):
        self.mailto = mailto or "agent@example.com"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": f"HFPCrawler/1.0 (mailto:{self.mailto})",
                "Accept": "application/json",
            }
        )
        self._cache: dict = {}

    def title_to_doi(self, title: str) -> list[dict]:
        """Search DOI by title"""
        try:
            resp = self.session.get(
                f"{self.BASE}/works",
                params={"query": title, "rows": 5},
                timeout=15,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            items = data.get("message", {}).get("items", [])
            results = []
            for item in items:
                item_title = (item.get("title") or [""])[0]
                doi = item.get("DOI", "")
                if doi:
                    # Try extracting arXiv info from BibTeX
                    arxiv = self._extract_arxiv_from_item(item)
                    results.append(
                        {
                            "doi": doi,
                            "title": item_title,
                            "arxiv_id": arxiv or "",
                            "venue": (item.get("container-title") or [""])[0],
                            "year": self._extract_year(item),
                            "score": item.get("score", 0),
                        }
                    )
            return results
        except Exception as e:
            logger.warning(f"[Crossref] title_to_doi failed: {e}")
            return []

    def doi_to_details(self, doi: str) -> Optional[dict]:
        """DOI → paper details (with manually extracted arXiv ID)"""
        try:
            resp = self.session.get(
                f"{self.BASE}/works/{doi}",
                timeout=15,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            item = data.get("message", {})
            arxiv = self._extract_arxiv_from_item(item)
            return {
                "doi": doi,
                "title": (item.get("title") or [""])[0],
                "arxiv_id": arxiv or "",
                "venue": (item.get("container-title") or [""])[0],
                "year": self._extract_year(item),
                "authors": json.dumps(
                    [f"{a.get('given', '')} {a.get('family', '')}" for a in item.get("author", [])],
                    ensure_ascii=False,
                ),
            }
        except Exception as e:
            logger.warning(f"[Crossref] doi_to_details failed: {e}")
            return None

    def cross_verify(self, arxiv_id: str, title: str) -> Optional[dict]:
        """Cross validation: arXiv ID + title → DOI

        Query Crossref by title → get DOI list → match most similar title
        → Return match result (with DOI, venue, confidence)
        """
        results = self.title_to_doi(title)
        if not results:
            return None

        from hfpapers.evolved import HFPapersCrawler

        best = None
        best_sim = 0.0

        for r in results:
            # Title similarity
            sim = HFPapersCrawler._title_similarity(title, r["title"])
            if sim > best_sim:
                best_sim = sim
                best = r

        if best and best_sim >= 0.3:
            return {
                "arxiv_id": arxiv_id,
                "doi": best["doi"],
                "title": best["title"],
                "venue": best["venue"],
                "year": best["year"],
                "confidence": min(best_sim + 0.2, 1.0),  # Title match + bonus
            }

        return None

    @staticmethod
    def _extract_arxiv_from_item(item: dict) -> Optional[str]:
        """Extract arXiv ID from Crossref item"""
        # Relation fields
        for rel_type, targets in item.get("relation", {}).items():
            for t in targets:
                val = t.get("id", "")
                m = ARXIV_ID_RE.search(str(val))
                if m:
                    return m.group(1)

        # Full-field text search
        all_text = str(item)
        m = ARXIV_ID_RE.search(all_text)
        return m.group(1) if m else None

    @staticmethod
    def _extract_year(item: dict) -> int:
        for key in ("published-print", "published-online", "issued", "created"):
            parts = item.get(key, {})
            dp = parts.get("date-parts", [[]])
            if dp and dp[0]:
                return dp[0][0]
        return 0


# ─── High-level Interface ────────────────────────────────


_store_instance: PaperStore | None = None
_crossref_instance: CrossrefClient | None = None


def get_store() -> PaperStore:
    global _store_instance
    if _store_instance is None:
        _store_instance = PaperStore()
    return _store_instance


def get_crossref() -> CrossrefClient:
    global _crossref_instance
    if _crossref_instance is None:
        _crossref_instance = CrossrefClient()
    return _crossref_instance


def ensure_paper(
    arxiv_id: str,
    title: str = "",
    source: str = "",
    abstract: str = "",
    venue: str = "",
    code_url: str = "",
    relevance: int = 0,
    doi: str = "",
) -> tuple[int, bool]:
    """Ensure paper exists, returns (sf_id, is_new).

    Looks up existing record by arxiv_id, creates if not exists.
    Then attempts (async/lazy) cross-validation via Crossref.
    """
    store = get_store()
    existing = None

    # Try lookup by arxiv_id first
    if arxiv_id:
        existing = store.get_paper_by_identifier("arxiv", arxiv_id)

    # Fallback: lookup by DOI (for CNS/non-arxiv papers)
    if not existing and doi:
        existing = store.get_paper_by_identifier("doi", doi)

    if existing:
        # Update info
        changed = False
        if title and not existing.title:
            existing.title = title
            changed = True
        if abstract and not existing.abstract:
            existing.abstract = abstract
            changed = True
        if venue and not existing.venue:
            existing.venue = venue
            changed = True
        if code_url and not existing.code_url:
            existing.code_url = code_url
            existing.has_code = True
            changed = True
        if relevance > existing.relevance:
            existing.relevance = relevance
            changed = True
        if changed:
            store.upsert_paper(existing)
        return existing.sf_id, False

    # Create new record
    record = PaperRecord(
        title=title[:500],
        abstract=abstract[:2000],
        source=source or "unknown",
        venue=venue,
        relevance=relevance,
        code_url=code_url,
        has_code=bool(code_url),
    )
    sf_id = store.upsert_paper(record)

    # Add arxiv identifier (skip if empty — DOI-only CNS papers)
    if arxiv_id:
        store.add_identifier(sf_id, "arxiv", arxiv_id, source=source)

    # Add DOI identifier if provided
    if doi:
        store.add_identifier(sf_id, "doi", doi, source=source)

    # If title is provided, try Crossref validation
    if title and arxiv_id:
        try:
            cr = get_crossref()
            result = cr.cross_verify(arxiv_id, title)
            if result and result.get("doi"):
                doi = result["doi"]
                store.add_identifier(
                    sf_id,
                    "doi",
                    doi,
                    source="crossref",
                    confidence=result["confidence"],
                )
                if result.get("venue"):
                    record = store.get_paper_by_id(sf_id)
                    if record and not record.venue:
                        record.venue = result["venue"]
                        record.year = result.get("year", 0)
                        store.upsert_paper(record)
                store.verify_paper(sf_id)
                logger.info(f"[CROSSREF] {arxiv_id} → DOI={doi} (conf={result['confidence']:.2f})")
        except Exception as e:
            logger.debug(f"[CROSSREF] {arxiv_id} Search failed: {e}")

    return sf_id, True


# ─── Statistics ────────────────────────────────────


def store_stats() -> dict:
    """View storage statistics"""
    store = get_store()
    with store._conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        verified = conn.execute("SELECT COUNT(*) FROM papers WHERE verified=1").fetchone()[0]
        with_code = conn.execute("SELECT COUNT(*) FROM papers WHERE has_code=1").fetchone()[0]
        id_count = conn.execute("SELECT COUNT(*) FROM identifiers").fetchone()[0]
        id_types = conn.execute(
            "SELECT id_type, COUNT(*) FROM identifiers GROUP BY id_type"
        ).fetchall()
        return {
            "papers_total": total,
            "papers_verified": verified,
            "papers_with_code": with_code,
            "identifiers_total": id_count,
            "identifiers_by_type": dict(id_types),
        }


# ─── Simple Test ────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        stats = store_stats()
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "ensure":
        aid = sys.argv[2]
        title = sys.argv[3] if len(sys.argv) > 3 else ""
        sf_id, is_new = ensure_paper(aid, title=title, source="cli_test")
        print(f"{'New' if is_new else 'Existing'}: sf_id={sf_id} {aid} {title[:40]}")

        paper = get_store().get_paper_by_id(sf_id)
        ids = get_store().get_identifiers(sf_id)
        print(f"  Title: {paper.title}")
        print(f"  Identifiers: {[(i.id_type, i.id_value) for i in ids]}")
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "search":
        keyword = sys.argv[2] if len(sys.argv) > 2 else ""
        papers = get_store().search_papers(keyword)
        print(f"Found {len(papers)} papers:")
        for p in papers:
            ids = get_store().get_identifiers(p.sf_id)
            id_str = ", ".join(f"{i.id_type}={i.id_value}" for i in ids[:3])
            print(f"  [{p.sf_id}] {p.title[:50]} | {id_str}")
        sys.exit(0)

    # Default: test
    print("=== Testing PaperStore ===")
    store = get_store()
    print(f"DB: {store.db_path}")

    # Create
    sf_id, is_new = ensure_paper(
        "9999.99999",
        title="Test Paper for SQLite Store",
        source="paper_store_test",
        abstract="This is a test abstract for the paper store module.",
        venue="TestConf 2025",
        relevance=50,
    )
    print(f"Paper: sf_id={sf_id} new={is_new}")

    # Search
    p = store.get_paper_by_id(sf_id)
    print(f"  Search: {p.title}")

    p2 = store.get_paper_by_identifier("arxiv", "9999.99999")
    print(f"  By ID: {p2.title if p2 else 'NOT FOUND'}")

    ids = store.get_identifiers(sf_id)
    print(f"  Identifiers: {[(i.id_type, i.id_value) for i in ids]}")

    # Cross validation
    store.verify_paper(sf_id)
    p3 = store.get_paper_by_id(sf_id)
    print(f"  Verified: {p3.verified}")
