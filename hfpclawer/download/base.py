#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BaseDownloader — Base downloader with progress tracking, checksum verification, and download_state table read/write."""

import hashlib
import json
import logging
import os
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger("hfpclawer.download.base")

# ─── download_state table ─────────────────────────────────
STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS download_state (
    source TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending',
    total_fetched INTEGER DEFAULT 0,
    total_new INTEGER DEFAULT 0,
    last_update TEXT,
    checksum TEXT DEFAULT '',
    error TEXT DEFAULT ''
);
"""


class ResumeState:
    """Resume state — read/write download_state table + JSON fallback"""

    def __init__(self, db_path: str, source: str):
        self.db_path = db_path
        self.source = source
        self._lock = threading.Lock()
        self._state_dir = os.path.dirname(db_path)
        self._json_path = os.path.join(self._state_dir, f"{source}_download_state.json")
        self._init_table()

    def _write_json_fallback(self, state: dict):
        """Write state to JSON file as fallback persistence"""
        try:
            os.makedirs(self._state_dir, exist_ok=True)
            with open(self._json_path, "w") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[{self.source}] JSON fallback write failed: {e}")

    def _read_json_fallback(self) -> dict:
        """Try to read state from JSON fallback"""
        try:
            if os.path.exists(self._json_path):
                with open(self._json_path) as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"[{self.source}] JSON fallback read failed: {e}")
        return {}

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_table(self):
        with self._conn() as conn:
            conn.execute(STATE_SCHEMA)
            conn.commit()

    def get(self) -> dict:
        """Read current state (SQLite first, fallback JSON)"""
        with self._lock, self._conn() as conn:
            r = conn.execute(
                "SELECT * FROM download_state WHERE source = ?", (self.source,)
            ).fetchone()
        if r:
            return dict(r)
        # fallback: JSON file
        fb = self._read_json_fallback()
        if fb:
            return fb
        return {"source": self.source, "status": "pending"}

    def set_status(self, status: str, checksum: str = "", error: str = ""):
        """Update status"""
        now = datetime.now().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO download_state
                   (source, status, total_fetched, total_new, last_update, checksum, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (self.source, status, 0, 0, now, checksum, error),
            )
            conn.commit()
        # JSON fallback
        self._write_json_fallback({
            "source": self.source,
            "status": status,
            "total_new": 0,
            "total_fetched": 0,
            "last_update": now,
            "checksum": checksum,
            "error": error,
        })

    def update_progress(self, total_fetched: int = 0, total_new: int = 0,
                        checksum: str = "", error: str = ""):
        """Update progress (incremental accumulation)"""
        now = datetime.now().isoformat()
        with self._lock, self._conn() as conn:
            conn.execute(
                """INSERT INTO download_state (source, status, total_fetched, total_new,
                    last_update, checksum, error)
                   VALUES (?, 'running', ?, ?, ?, ?, ?)
                   ON CONFLICT(source) DO UPDATE SET
                       status = 'running',
                       total_fetched = total_fetched + ?,
                       total_new = total_new + ?,
                       last_update = ?,
                       checksum = COALESCE(NULLIF(?, ''), checksum),
                       error = COALESCE(NULLIF(?, ''), error)""",
                (self.source, total_fetched, total_new,
                 now, checksum, error,
                 total_fetched, total_new,
                 now, checksum, error),
            )
            conn.commit()
        # JSON fallback
        self._write_json_fallback({
            "source": self.source,
            "status": "running",
            "total_new": total_new,
            "total_fetched": total_fetched,
            "last_update": now,
            "checksum": checksum,
            "error": error,
        })

    def mark_done(self):
        """Mark done"""
        self.set_status("done")

    def mark_failed(self, error_msg: str):
        """Mark failed"""
        self.set_status("failed", error=error_msg[:500])

    def checksum_file(self, filepath: str) -> str:
        """Calculate file MD5"""
        md5 = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(64 * 1024 * 1024), b""):
                md5.update(chunk)
        return md5.hexdigest()

    @staticmethod
    def date_range_to_checksum(from_date: str, to_date: str = "") -> str:
        """OAI source: encode date range as checksum"""
        if not to_date:
            to_date = datetime.now().strftime("%Y-%m-%d")
        return f"{from_date}:{to_date}"

    @staticmethod
    def parse_date_range(checksum: str) -> tuple[str, str]:
        """Parse OAI date range checksum"""
        parts = checksum.split(":")
        if len(parts) == 2:
            return parts[0], parts[1]
        return "", ""


class BaseDownloader(ABC):
    """Base downloader class

    Subclasses must implement:
        - source_name: str constant (e.g. 'oai', 'kaggle')
        - run(): Actual download logic
        - Call self._update_progress() from run() to report progress
    """

    source_name: str = "base"

    def __init__(self, db_path: str = "", progress_cb: Optional[Callable] = None):
        self.db_path = db_path or self._default_db_path()
        self.progress_cb = progress_cb
        self.state = ResumeState(self.db_path, self.source_name)
        self._interrupted = False

    @abstractmethod
    def _default_db_path(self) -> str:
        """Default database path"""
        ...

    @abstractmethod
    def run(self, **kwargs) -> int:
        """Execute download, return number of new records"""
        ...

    def bump_version(self):
        """Version marker"""
        pass

    def _update_progress(self, fetched: int, new_count: int, checksum: str = ""):
        """Update progress and notify callback"""
        self.state.update_progress(
            total_fetched=fetched,
            total_new=new_count,
            checksum=checksum,
        )
        if self.progress_cb:
            self.progress_cb({
                "source": self.source_name,
                "fetched": fetched,
                "new": new_count,
            })

    def interrupt(self):
        """Request interruption"""
        self._interrupted = True

    @property
    def status(self) -> dict:
        """Current download status"""
        return self.state.get()
