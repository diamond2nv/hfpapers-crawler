"""BaseDownloader — 下载器基类，提供进度跟踪、checksum 校验、download_state 表读写。"""

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("hfpclawer.download.base")

# ─── download_state 表 ─────────────────────────────────
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
    """断点续传状态 — 读写 download_state 表 + JSON fallback"""

    def __init__(self, db_path: str, source: str):
        self.db_path = db_path
        self.source = source
        self._lock = threading.Lock()
        self._state_dir = os.path.dirname(db_path)
        self._json_path = os.path.join(self._state_dir, f"{source}_download_state.json")
        self._init_table()

    def _write_json_fallback(self, state: dict):
        """将状态写入 JSON 文件作为 fallback 持久化"""
        try:
            os.makedirs(self._state_dir, exist_ok=True)
            with open(self._json_path, "w") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[{self.source}] JSON fallback 写入失败: {e}")

    def _read_json_fallback(self) -> dict:
        """尝试从 JSON fallback 读取状态"""
        try:
            if os.path.exists(self._json_path):
                with open(self._json_path) as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"[{self.source}] JSON fallback 读取失败: {e}")
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
        """读取当前状态（优先 SQLite，fallback JSON）"""
        with self._lock, self._conn() as conn:
            r = conn.execute(
                "SELECT * FROM download_state WHERE source = ?", (self.source,)
            ).fetchone()
        if r:
            return dict(r)
        # fallback: JSON 文件
        fb = self._read_json_fallback()
        if fb:
            return fb
        return {"source": self.source, "status": "pending"}

    def set_status(self, status: str, checksum: str = "", error: str = ""):
        """更新状态"""
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
        """更新进度（增量累加）"""
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
        """标记完成"""
        self.set_status("done")

    def mark_failed(self, error_msg: str):
        """标记失败"""
        self.set_status("failed", error=error_msg[:500])

    def checksum_file(self, filepath: str) -> str:
        """计算文件 MD5"""
        md5 = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(64 * 1024 * 1024), b""):
                md5.update(chunk)
        return md5.hexdigest()

    @staticmethod
    def date_range_to_checksum(from_date: str, to_date: str = "") -> str:
        """OAI 源: 日期范围编码为 checksum"""
        if not to_date:
            to_date = datetime.now().strftime("%Y-%m-%d")
        return f"{from_date}:{to_date}"

    @staticmethod
    def parse_date_range(checksum: str) -> tuple[str, str]:
        """解析 OAI 日期范围 checksum"""
        parts = checksum.split(":")
        if len(parts) == 2:
            return parts[0], parts[1]
        return "", ""


class BaseDownloader(ABC):
    """下载器基类

    子类需实现:
        - source_name: str 常量（如 'oai', 'kaggle'）
        - run(): 实际下载逻辑
        - 在 run() 中调用 self._update_progress() 报告进度
    """

    source_name: str = "base"

    def __init__(self, db_path: str = "", progress_cb: Optional[Callable] = None):
        self.db_path = db_path or self._default_db_path()
        self.progress_cb = progress_cb
        self.state = ResumeState(self.db_path, self.source_name)
        self._interrupted = False

    @abstractmethod
    def _default_db_path(self) -> str:
        """默认数据库路径"""
        ...

    @abstractmethod
    def run(self, **kwargs) -> int:
        """执行下载，返回新增条数"""
        ...

    def bump_version(self):
        """版本标记"""
        pass

    def _update_progress(self, fetched: int, new_count: int, checksum: str = ""):
        """更新进度并通知回调"""
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
        """请求中断"""
        self._interrupted = True

    @property
    def status(self) -> dict:
        """当前下载状态"""
        return self.state.get()
