#!/usr/bin/env python3
"""
paper_store.py — 论文统一存储引擎

功能:
  - 雪花 ID 生成器 (Snowflake ID, 64-bit)
  - SQLite 统一存储: papers 主表 + identifiers 映射表
  - 多标识符交叉验证: arXiv ID ↔ DOI ↔ OpenReview Forum ↔ ISSN ↔ PNS
  - Crossref API 查询: title→DOI, DOI→arXiv (eprint)

架构:
                   ┌──────────────────┐
                   │   paper_store    │
                   ├──────────────────┤
                   │ Snowflake ID gen │
                   │ SQLite (3 表)    │
                   │ Crossref client  │
                   └────────┬─────────┘
                            │
          ┌─────────────────┼──────────────────┐
          ▼                 ▼                   ▼
   pipeline.py        evolved.py          sources.py
   (Scrapy)           (CLI 爬虫)          (多源搜索)

状态管理:
  - 去重文件 ~/wiki/raw/papers/hfpapers-crawled.json 继续保留
  - SQLite 作为权威数据源，JSON 作为快速查询缓存
  - 迁移过渡期双写
"""

import json
import logging
import os
import re
import sqlite3
import threading
import time
import requests
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

from hfpapers.config import get as cfg_get

logger = logging.getLogger("hfpapers.paper_store")

# ─── 常量 ───────────────────────────────────
ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")
DOI_RE = re.compile(r"10\.\d{4,}/[^\s]+")

# ─── 雪花 ID 生成器（yitter 雪花漂移算法）────
# 来源: https://github.com/yitter/IdGenerator
# 优化的雪花算法 — 支持时间回拨处理、更短ID、更高性能
# 线程安全，单机 50W/0.1s 并发能力
#
# 外部接口（保持兼容）:
#   snowflake_id(worker_id=None) -> int
#   snowflake_timestamp(sf_id) -> datetime
#   init_snowflake_worker(worker_id)  — 初始化 WorkerId
#
# WorkerId 配置优先级:
#   1. 显式调用 init_snowflake_worker()
#   2. _TEST_SNOWFLAKE_WORKER 环境变量
#   3. 配置文件 snowflake.worker_id
#   4. PID 哈希到 0-63 (fallback)

_SNOWFLAKE_LOCK = threading.Lock()
_SNOWFLAKE_GEN: Optional["_SnowflakeM1"] = None
_SNOWFLAKE_WORKER_ID: int = 0
_SNOWFLAKE_BASE_TIME: int = 1728000000000  # 2024-10-04


class _IdGeneratorOptions:
    """雪花漂移算法配置选项"""

    def __init__(self, worker_id: int = 0):
        self.method: int = 1                   # 1=漂移算法
        self.base_time: int = _SNOWFLAKE_BASE_TIME
        self.worker_id: int = worker_id
        self.worker_id_bit_length: int = 6     # [1,15] WorkerId 范围 0-63
        self.seq_bit_length: int = 6           # [3,21] 每毫秒基础 64 ID
        self.max_seq_number: int = 0           # 0=自动 (2^seq_bit_length-1)
        self.min_seq_number: int = 5           # 前5个保留位(回拨预留)
        self.top_over_cost_count: int = 2000   # 最大漂移次数


class _SnowflakeM1:
    """雪花漂移算法 M1 实现"""

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
            # 时间回拨处理
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
    """决定 WorkerId 值"""
    # 1. 环境变量
    env_wid = os.environ.get("_TEST_SNOWFLAKE_WORKER")
    if env_wid:
        return int(env_wid)
    # 2. 配置文件
    try:
        cfg_wid = cfg_get("snowflake.worker_id", 0)
        if cfg_wid:
            return int(cfg_wid)
    except Exception:
        pass
    # 3. fallback: PID 哈希到 0-63
    pid = os.getpid()
    return (pid * 2654435761) & 0x3F  # Knuth 乘数哈希


def _get_snowflake() -> _SnowflakeM1:
    """获取/初始化雪花生成器单例"""
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
    """显式初始化 WorkerId（分布式部署时使用）"""
    global _SNOWFLAKE_GEN, _SNOWFLAKE_WORKER_ID
    with _SNOWFLAKE_LOCK:
        _SNOWFLAKE_WORKER_ID = worker_id
        opts = _IdGeneratorOptions(worker_id=worker_id)
        _SNOWFLAKE_GEN = _SnowflakeM1(opts)
        logger.info(f"Snowflake re-initialized: worker_id={worker_id}")


def snowflake_id(worker_id: int = None) -> int:
    """生成雪花 ID（保持兼容接口）

    如果传递 worker_id，会在当前线程中覆盖使用指定 worker_id，
    但不影响全局生成器。全局生成器使用自动解析的 worker_id。
    """
    if worker_id is not None:
        # 临时用指定 worker_id 生成（用于测试）
        opts = _IdGeneratorOptions(worker_id=worker_id)
        gen = _SnowflakeM1(opts)
        return gen.next_id()
    return _get_snowflake().next_id()


def snowflake_timestamp(sf_id: int) -> datetime:
    """从雪花 ID 提取时间戳（保持兼容接口）

    注意: yitter 的 ID 位布局:
      ID = (time_tick << shift) + (worker_id << seq_bit) + seq
    其中 time_tick = 当前毫秒 - base_time
    因此 time_tick = sf_id >> shift （当 seq和worker不超位宽时）
    """
    shift = 12  # 默认6+6
    try:
        if _SNOWFLAKE_GEN:
            shift = _SNOWFLAKE_GEN._timestamp_shift
    except Exception:
        pass
    time_tick = sf_id >> shift
    ms = time_tick + _SNOWFLAKE_BASE_TIME
    return datetime.fromtimestamp(ms / 1000.0)


# ─── 数据模型 ───────────────────────────────


@dataclass
class PaperRecord:
    """论文主记录"""
    sf_id: int = 0               # 雪花 ID
    title: str = ""
    abstract: str = ""
    year: int = 0
    source: str = ""             # 首次发现来源
    venue: str = ""              # 会议/期刊全名
    relevance: int = 0           # 相关度 0-100
    has_code: bool = False
    code_url: str = ""
    verified: bool = False       # 是否经过交叉验证
    created_at: str = ""
    updated_at: str = ""


@dataclass
class PaperIdentifier:
    """论文标识符映射 (N:1 → PaperRecord)"""
    sf_id: int                   # 关联的论文雪花 ID
    id_type: str                 # "arxiv" / "doi" / "openreview" / "issn" / "pns" / "isbn"
    id_value: str                # 标识符值
    source: str = ""             # 此 ID 的来源
    confidence: float = 1.0      # 置信度 0-1
    verified_at: str = ""        # 验证时间


# ─── SQLite 存储层 ──────────────────────────


def _db_path() -> str:
    """数据库文件路径"""
    base = cfg_get("paths.data_dir", "data")
    # 如果 base 是相对路径，则相对于项目根
    if not os.path.isabs(base):
        base = os.path.join(os.path.dirname(os.path.dirname(__file__)), base)
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "papers.db")


class PaperStore:
    """论文存储引擎 — SQLite 后端"""

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
        """初始化表结构"""
        with self._lock, self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS papers (
                    sf_id       INTEGER PRIMARY KEY,  -- 雪花 ID
                    title       TEXT NOT NULL DEFAULT '',
                    abstract    TEXT DEFAULT '',
                    year        INTEGER DEFAULT 0,
                    source      TEXT DEFAULT '',       -- 首次来源
                    venue       TEXT DEFAULT '',       -- 会议/期刊
                    relevance   INTEGER DEFAULT 0,     -- 相关度 0-100
                    has_code    INTEGER DEFAULT 0,     -- 是否有代码
                    code_url    TEXT DEFAULT '',
                    verified    INTEGER DEFAULT 0,     -- 是否经过交叉验证
                    created_at  TEXT DEFAULT (datetime('now')),
                    updated_at  TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS identifiers (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    sf_id       INTEGER NOT NULL,       -- 关联论文
                    id_type     TEXT NOT NULL,            -- arxiv/doi/openreview/issn/pns
                    id_value    TEXT NOT NULL,            -- 标识符值
                    source      TEXT DEFAULT '',          -- 此 ID 的来源
                    confidence  REAL DEFAULT 1.0,         -- 置信度
                    verified_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(id_type, id_value),
                    FOREIGN KEY (sf_id) REFERENCES papers(sf_id)
                );

                CREATE TABLE IF NOT EXISTS crossref_cache (
                    doi         TEXT PRIMARY KEY,
                    title       TEXT DEFAULT '',
                    arxiv_id    TEXT DEFAULT '',        -- 从 BibTeX eprint 提取
                    venue       TEXT DEFAULT '',
                    authors     TEXT DEFAULT '',        -- JSON array
                    year        INTEGER DEFAULT 0,
                    raw_json    TEXT DEFAULT '',        -- 原始响应摘要
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

    # ─── 论文 CRUD ───────────────────────────

    def upsert_paper(self, record: PaperRecord) -> int:
        """写入或更新论文。返回 sf_id。"""
        with self._lock, self._conn() as conn:
            if record.sf_id:
                # 更新
                conn.execute("""
                    UPDATE papers SET
                        title=?, abstract=?, year=?, source=?,
                        venue=?, relevance=?, has_code=?, code_url=?,
                        verified=?, updated_at=datetime('now')
                    WHERE sf_id=?
                """, (
                    record.title, record.abstract, record.year,
                    record.source, record.venue, record.relevance,
                    int(record.has_code), record.code_url,
                    int(record.verified), record.sf_id,
                ))
            else:
                # 插入
                sf_id = snowflake_id()
                record.sf_id = sf_id
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute("""
                    INSERT INTO papers
                        (sf_id, title, abstract, year, source, venue,
                         relevance, has_code, code_url, verified,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sf_id, record.title, record.abstract, record.year,
                    record.source, record.venue, record.relevance,
                    int(record.has_code), record.code_url,
                    int(record.verified), now, now,
                ))
                record.created_at = now
                record.updated_at = now
            return record.sf_id

    def get_paper_by_id(self, sf_id: int) -> Optional[PaperRecord]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE sf_id=?", (sf_id,)
            ).fetchone()
            if row:
                return self._row_to_record(row)
            return None

    def get_paper_by_identifier(self, id_type: str, id_value: str) -> Optional[PaperRecord]:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT p.* FROM papers p
                JOIN identifiers i ON p.sf_id = i.sf_id
                WHERE i.id_type=? AND i.id_value=?
            """, (id_type, id_value)).fetchone()
            if row:
                return self._row_to_record(row)
            return None

    def search_papers(self, keyword: str = "", limit: int = 50) -> list[PaperRecord]:
        with self._conn() as conn:
            if keyword:
                rows = conn.execute("""
                    SELECT * FROM papers
                    WHERE title LIKE ? OR abstract LIKE ?
                    ORDER BY relevance DESC, created_at DESC
                    LIMIT ?
                """, (f"%{keyword}%", f"%{keyword}%", limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM papers
                    ORDER BY relevance DESC, created_at DESC
                    LIMIT ?
                """, (limit,)).fetchall()
            return [self._row_to_record(r) for r in rows]

    def update_paper(self, sf_id: int, **kwargs) -> bool:
        """更新论文的指定字段 (relevance/code_url/venue)"""
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
            logger.warning(f"update_paper 失败: {e}")
            return False

    def stats(self) -> dict:
        """统计信息（同 store_stats()）"""
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

    # ─── 标识符管理 ──────────────────────────

    def add_identifier(self, sf_id: int, id_type: str, id_value: str,
                       source: str = "", confidence: float = 1.0) -> bool:
        """为论文添加一个标识符映射。已存在则跳过。"""
        try:
            with self._lock, self._conn() as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO identifiers
                        (sf_id, id_type, id_value, source, confidence)
                    VALUES (?, ?, ?, ?, ?)
                """, (sf_id, id_type, id_value, source, confidence))
                return True
        except Exception as e:
            logger.warning(f"add_identifier 失败: {e}")
            return False

    def get_identifiers(self, sf_id: int) -> list[PaperIdentifier]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM identifiers WHERE sf_id=?", (sf_id,)
            ).fetchall()
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
        """通过任意标识符值查找论文（自动识别类型）"""
        # 先尝试直接匹配
        for id_type in ("arxiv", "doi", "openreview", "issn", "pns", "isbn"):
            paper = self.get_paper_by_identifier(id_type, id_value)
            if paper:
                return paper

        # 尝试 ARXIV_ID_RE 匹配
        m = ARXIV_ID_RE.search(id_value)
        if m:
            paper = self.get_paper_by_identifier("arxiv", m.group(1))
            if paper:
                return paper

        # 尝试 DOI_RE 匹配
        m = DOI_RE.search(id_value)
        if m:
            paper = self.get_paper_by_identifier("doi", m.group(0))
            if paper:
                return paper

        return None

    # ─── 交叉验证 ────────────────────────────

    def verify_paper(self, sf_id: int) -> bool:
        """检查论文是否有 ≥2 个标识符来自不同源，标记为已验证"""
        ids = self.get_identifiers(sf_id)
        types = set(i.id_type for i in ids)
        if len(types) >= 2:
            with self._lock, self._conn() as conn:
                conn.execute(
                    "UPDATE papers SET verified=1, updated_at=datetime('now') WHERE sf_id=?",
                    (sf_id,)
                )
            return True
        return False


# ─── Crossref 客户端 ─────────────────────────


class CrossrefClient:
    """Crossref API 客户端 — DOI 查询 + 交叉验证"""

    BASE = "https://api.crossref.org"

    def __init__(self, mailto: str = ""):
        self.mailto = mailto or "agent@example.com"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"HFPCrawler/1.0 (mailto:{self.mailto})",
            "Accept": "application/json",
        })
        self._cache: dict = {}

    def title_to_doi(self, title: str) -> list[dict]:
        """通过标题搜索 DOI"""
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
                    # 尝试从 BibTeX 中提取 arXiv 信息
                    arxiv = self._extract_arxiv_from_item(item)
                    results.append({
                        "doi": doi,
                        "title": item_title,
                        "arxiv_id": arxiv or "",
                        "venue": (item.get("container-title") or [""])[0],
                        "year": self._extract_year(item),
                        "score": item.get("score", 0),
                    })
            return results
        except Exception as e:
            logger.warning(f"[Crossref] title_to_doi 失败: {e}")
            return []

    def doi_to_details(self, doi: str) -> Optional[dict]:
        """DOI → 论文详情（含人工提取的 arXiv ID）"""
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
                "authors": json.dumps([
                    f"{a.get('given','')} {a.get('family','')}"
                    for a in item.get("author", [])
                ], ensure_ascii=False),
            }
        except Exception as e:
            logger.warning(f"[Crossref] doi_to_details 失败: {e}")
            return None

    def cross_verify(self, arxiv_id: str, title: str) -> Optional[dict]:
        """交叉验证: arXiv ID + title → DOI

        用 title 查 Crossref → 得到 DOI 列表 → 匹配最相似的标题
        → 返回匹配结果（含 DOI、venue、可信度）
        """
        results = self.title_to_doi(title)
        if not results:
            return None

        from hfpapers.evolved import HFPapersCrawler

        best = None
        best_sim = 0.0

        for r in results:
            # 标题相似度
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
                "confidence": min(best_sim + 0.2, 1.0),  # 标题匹配 + 加分
            }

        return None

    @staticmethod
    def _extract_arxiv_from_item(item: dict) -> Optional[str]:
        """从 Crossref item 中提取 arXiv ID"""
        # 关系字段
        for rel_type, targets in item.get("relation", {}).items():
            for t in targets:
                val = t.get("id", "")
                m = ARXIV_ID_RE.search(str(val))
                if m:
                    return m.group(1)

        # 全字段文本搜索
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


# ─── 高层接口 ────────────────────────────────


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


def ensure_paper(arxiv_id: str, title: str = "", source: str = "",
                 abstract: str = "", venue: str = "",
                 code_url: str = "", relevance: int = 0) -> tuple[int, bool]:
    """确保论文存在，返回 (sf_id, is_new)。

    会根据 arxiv_id 查找已有记录，若不存在则创建。
    然后尝试（异步/懒）通过 Crossref 交叉验证。
    """
    store = get_store()
    existing = store.get_paper_by_identifier("arxiv", arxiv_id)

    if existing:
        # 更新信息
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
            changed = True
        if relevance > existing.relevance:
            existing.relevance = relevance
            changed = True
        if changed:
            store.upsert_paper(existing)
        return existing.sf_id, False

    # 创建新记录
    record = PaperRecord(
        title=title[:500],
        abstract=abstract[:2000],
        source=source or "unknown",
        venue=venue,
        relevance=relevance,
        code_url=code_url,
    )
    sf_id = store.upsert_paper(record)
    store.add_identifier(sf_id, "arxiv", arxiv_id, source=source)

    # 如果给了 title，尝试 Crossref 验证
    if title:
        try:
            cr = get_crossref()
            result = cr.cross_verify(arxiv_id, title)
            if result and result.get("doi"):
                doi = result["doi"]
                store.add_identifier(
                    sf_id, "doi", doi, source="crossref",
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
            logger.debug(f"[CROSSREF] {arxiv_id} 查询失败: {e}")

    return sf_id, True


# ─── 统计 ────────────────────────────────────


def store_stats() -> dict:
    """查看存储统计"""
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


# ─── 简单测试 ────────────────────────────────

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
        print(f"{'新建' if is_new else '已有'}: sf_id={sf_id} {aid} {title[:40]}")

        paper = get_store().get_paper_by_id(sf_id)
        ids = get_store().get_identifiers(sf_id)
        print(f"  标题: {paper.title}")
        print(f"  标识符: {[(i.id_type, i.id_value) for i in ids]}")
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "search":
        keyword = sys.argv[2] if len(sys.argv) > 2 else ""
        papers = get_store().search_papers(keyword)
        print(f"找到 {len(papers)} 篇论文:")
        for p in papers:
            ids = get_store().get_identifiers(p.sf_id)
            id_str = ", ".join(f"{i.id_type}={i.id_value}" for i in ids[:3])
            print(f"  [{p.sf_id}] {p.title[:50]} | {id_str}")
        sys.exit(0)

    # 默认: 测试
    print("=== 测试 PaperStore ===")
    store = get_store()
    print(f"DB: {store.db_path}")

    # 创建
    sf_id, is_new = ensure_paper("9999.99999",
                                  title="Test Paper for SQLite Store",
                                  source="paper_store_test",
                                  abstract="This is a test abstract for the paper store module.",
                                  venue="TestConf 2025",
                                  relevance=50)
    print(f"Paper: sf_id={sf_id} new={is_new}")

    # 查询
    p = store.get_paper_by_id(sf_id)
    print(f"  查询: {p.title}")

    p2 = store.get_paper_by_identifier("arxiv", "9999.99999")
    print(f"  按 ID 查询: {p2.title if p2 else 'NOT FOUND'}")

    ids = store.get_identifiers(sf_id)
    print(f"  标识符: {[(i.id_type, i.id_value) for i in ids]}")

    # 交叉验证
    store.verify_paper(sf_id)
    p3 = store.get_paper_by_id(sf_id)
    print(f"  验证状态: {p3.verified}")
