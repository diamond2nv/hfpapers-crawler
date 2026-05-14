#!/usr/bin/env python3
"""
hfpapers/logger.py — Structured logging with rotation + audit trail

Features:
  - RotatingFileHandler (10MB × 5) for structured JSON logs
  - Dual output: console (INFO+) + file (DEBUG+)
  - Structured JSON records with paper_id / event / duration / version
  - Audit events tracked separately in audit DB
  - Batch-level tracking (batch_id, phase, status)

Usage:
    from hfpapers.logger import get_logger, get_audit

    log = get_logger("download_queue")
    log.info("Downloading", extra={"arxiv_id": "2001.08361", "batch_id": "b01"})

    audit = get_audit()
    audit.record(arxiv_id="2001.08361", event="download_start",
                 meta={"batch_id": "b01"})
    audit.record(arxiv_id="2001.08361", event="download_done",
                 duration_s=12.5)
"""

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).parent.parent
LOG_DIR = BASE_DIR / "logs"
AUDIT_DB_PATH = BASE_DIR / "data" / "audit.db"

os.makedirs(LOG_DIR, exist_ok=True)

# ─── Structured JSON Formatter ──────────────────────────


class JsonFormatter(logging.Formatter):
    """Log as one JSON line per record — machine-parseable"""

    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "time": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Extra structured fields from logging.extra dict
        for key in (
            "arxiv_id",
            "batch_id",
            "paper_id",
            "duration_s",
            "phase",
            "status",
            "event",
            "version",
        ):
            val = getattr(record, key, None)
            if val is not None:
                obj[key] = val
        # exc_info
        if record.exc_info and record.exc_info[0]:
            obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(obj, ensure_ascii=False)


# ─── Logger Factory ────────────────────────────────────


_LOG_INIT_LOCK = threading.Lock()
_LOG_INITIALIZED = False


def init_logging(level: int = logging.INFO):
    """Initialize root logger with dual output + rotation

    Call once at application startup.
    """
    global _LOG_INITIALIZED
    if _LOG_INITIALIZED:
        return
    with _LOG_INIT_LOCK:
        if _LOG_INITIALIZED:
            return

        root = logging.getLogger()
        root.setLevel(logging.DEBUG)

        # File handler — 10MB × 5, JSON
        fh = RotatingFileHandler(
            LOG_DIR / "hfpapers.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(JsonFormatter())
        root.addHandler(fh)

        # Console handler — plain text
        ch = logging.StreamHandler()
        ch.setLevel(level)
        ch.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(ch)

        _LOG_INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    """Get a named logger (auto-initializes if needed)"""
    if not _LOG_INITIALIZED:
        init_logging()
    return logging.getLogger(name)


# ─── Audit DB — persistent event trail ─────────────────

# Schema
_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time  TEXT NOT NULL DEFAULT (datetime('now')),
    arxiv_id    TEXT DEFAULT '',
    event       TEXT NOT NULL,         -- download_start/done/convert/wiki_sync
    batch_id    TEXT DEFAULT '',
    phase       TEXT DEFAULT '',       -- download / convert / wiki_sync / batch
    status      TEXT DEFAULT '',       -- pending / done / failed
    duration_s  REAL DEFAULT 0,
    version     TEXT DEFAULT 'hfpapers-dq-1.0',
    meta        TEXT DEFAULT '{}'      -- JSON extra context
);
CREATE INDEX IF NOT EXISTS idx_audit_arxiv ON audit_events(arxiv_id);
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_events(event);
CREATE INDEX IF NOT EXISTS idx_audit_time  ON audit_events(event_time);
CREATE INDEX IF NOT EXISTS idx_audit_batch ON audit_events(batch_id);
"""


class AuditTrail:
    """Persistent audit trail — SQLite-backed event log

    Tracks:
      - Every download attempt (success or failure)
      - Every MD conversion
      - Every wiki sync
      - Batch-level summary events
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(AUDIT_DB_PATH)
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        with self._lock, self._conn() as conn:
            conn.executescript(_AUDIT_SCHEMA)

    def record(
        self,
        arxiv_id: str = "",
        event: str = "",
        batch_id: str = "",
        phase: str = "",
        status: str = "",
        duration_s: float = 0,
        version: str = "",
        meta: dict = None,
    ):
        """Record a single audit event"""
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT INTO audit_events
                    (arxiv_id, event, batch_id, phase, status, duration_s,
                     version, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    arxiv_id,
                    event,
                    batch_id,
                    phase,
                    status,
                    duration_s,
                    version or "hfpapers-dq-1.0",
                    json.dumps(meta or {}, ensure_ascii=False),
                ),
            )

    def query(
        self, arxiv_id: str = "", event: str = "", batch_id: str = "", limit: int = 50
    ) -> list[dict]:
        """Query audit events with filters"""
        where = []
        params = []
        if arxiv_id:
            where.append("arxiv_id=?")
            params.append(arxiv_id)
        if event:
            where.append("event=?")
            params.append(event)
        if batch_id:
            where.append("batch_id=?")
            params.append(batch_id)

        sql = "SELECT * FROM audit_events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def stats(self, since: str = "") -> dict:
        """Aggregate audit statistics"""
        where = ""
        params = []
        if since:
            where = " WHERE event_time >= ?"
            params.append(since)

        with self._conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM audit_events{where}", params).fetchone()[0]

            by_event = conn.execute(
                f"SELECT event, COUNT(*) as cnt FROM audit_events{where} "
                "GROUP BY event ORDER BY cnt DESC",
                params,
            ).fetchall()

            if since and params:
                failure_sql = f"SELECT COUNT(*) FROM audit_events{where} AND status='failed'"
            else:
                failure_sql = "SELECT COUNT(*) FROM audit_events WHERE status='failed'"
            failures = conn.execute(failure_sql, params).fetchone()[0]

            return {
                "total_events": total,
                "by_event": dict(by_event),
                "total_failures": failures,
            }

    def batch_summary(self, batch_id: str) -> dict:
        """Get summary of events for a specific batch"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT event, status, COUNT(*) as cnt "
                "FROM audit_events WHERE batch_id=? "
                "GROUP BY event, status ORDER BY event",
                (batch_id,),
            ).fetchall()
            return {
                "batch_id": batch_id,
                "events": [dict(r) for r in rows],
            }

    def latest_batch(self) -> Optional[str]:
        """Get the most recent batch_id"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT batch_id FROM audit_events WHERE batch_id != '' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row["batch_id"] if row else None


# ─── Singleton ─────────────────────────────────────────


_audit_instance: Optional[AuditTrail] = None


def get_audit() -> AuditTrail:
    global _audit_instance
    if _audit_instance is None:
        _audit_instance = AuditTrail()
    return _audit_instance


def record_event(
    arxiv_id: str = "",
    event: str = "",
    batch_id: str = "",
    phase: str = "",
    status: str = "",
    duration_s: float = 0,
    meta: dict = None,
):
    """Convenience: record audit event without creating instance"""
    get_audit().record(
        arxiv_id=arxiv_id,
        event=event,
        batch_id=batch_id,
        phase=phase,
        status=status,
        duration_s=duration_s,
        meta=meta,
    )
