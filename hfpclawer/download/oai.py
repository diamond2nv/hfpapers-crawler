"""OaiPmhDownloader — arXiv OAI-PMH 元数据增量/全量下载器

从 scripts/download_arxiv_oai.py 提炼并适配 BaseDownloader。
支持断点续传、优先级队列、增量更新。
"""

import json
import logging
import os
import re
import sqlite3
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

from hfpclawer.download.base import BaseDownloader, ResumeState

logger = logging.getLogger("hfpclawer.download.oai")

# ─── 常量 ───────────────────────────────────
OAI_BASE = "https://export.arxiv.org/oai2"
MAX_RETRIES = 5
RETRY_BACKOFF = [2, 5, 10, 30, 60]
PAGE_SIZE = 1000
BATCH_WRITE = 500
RATE_LIMIT = 2.0

# ─── 下载优先级 ─────────────────────────────
DOWNLOAD_PRIORITIES = [
    "cs:cs:AI", "cs:cs:LG", "cs:cs:NA", "cs:cs:NE",
    "cs:cs:CV", "cs:cs:CL",
    "math:math:AP", "math:math:NA", "math:math:OC",
    "stat:stat:ML", "stat:stat:CO",
    "cs:cs:CE", "cs:cs:IR", "cs:cs:IT", "cs:cs:DS",
    "cs:cs:DB", "cs:cs:DC", "cs:cs:GT", "cs:cs:MA",
    "cs:cs:RO", "cs:cs:SC", "cs:cs:SY", "cs:cs:AR",
    "cs:cs:CC", "cs:cs:CG", "cs:cs:CR", "cs:cs:CY",
    "cs:cs:DL", "cs:cs:DM", "cs:cs:ET", "cs:cs:FL",
    "cs:cs:GL", "cs:cs:GR", "cs:cs:HC", "cs:cs:LO",
    "cs:cs:MM", "cs:cs:MS", "cs:cs:NI", "cs:cs:OH",
    "cs:cs:OS", "cs:cs:PF", "cs:cs:PL", "cs:cs:SD",
    "cs:cs:SE", "cs:cs:SI", "cs:cs:OH",
    "math:math:CO", "math:math:DS", "math:math:FA",
    "math:math:KT", "math:math:LO", "math:math:MP",
    "math:math:NT", "math:math:OA", "math:math:PR",
    "math:math:QA", "math:math:RA", "math:math:RT",
    "math:math:SG", "math:math:SP", "math:math:ST",
    "math:math:AC", "math:math:AG", "math:math:AT",
    "math:math:CA", "math:math:CT", "math:math:CV",
    "math:math:DG", "math:math:GN", "math:math:GR",
    "math:math:GT", "math:math:HO", "math:math:MG", "math:math:QA",
    "stat:stat:AP", "stat:stat:ME", "stat:stat:OT", "stat:stat:TH",
]

# ─── FTS5 Schema ────────────────────────────
FTS_SCHEMA = """CREATE VIRTUAL TABLE IF NOT EXISTS arxiv_fts USING fts5(
    arxiv_id UNINDEXED, title, authors, abstract, categories UNINDEXED,
    doi UNINDEXED, journal_ref UNINDEXED, update_date UNINDEXED,
    tokenize='porter unicode61');"""

META_SCHEMA = """CREATE TABLE IF NOT EXISTS arxiv_meta (
    arxiv_id TEXT PRIMARY KEY, title TEXT, authors TEXT, abstract TEXT,
    categories TEXT, doi TEXT, journal_ref TEXT, update_date TEXT,
    imported_at TEXT DEFAULT (datetime('now')));
CREATE INDEX IF NOT EXISTS idx_arxiv_meta_date ON arxiv_meta(update_date);
CREATE INDEX IF NOT EXISTS idx_arxiv_meta_cat ON arxiv_meta(categories);
CREATE INDEX IF NOT EXISTS idx_arxiv_meta_doi ON arxiv_meta(doi);"""


class ArxivMetaDB:
    """arXiv 元数据 SQLite 存储（低层封装）"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA cache_size=-80000")
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(FTS_SCHEMA)
            conn.executescript(META_SCHEMA)

    def insert_batch(self, papers: list[tuple]):
        with self._lock, self._conn() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO arxiv_meta
                   (arxiv_id, title, authors, abstract, categories,
                    doi, journal_ref, update_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", papers)
            conn.executemany(
                """INSERT OR IGNORE INTO arxiv_fts
                   (arxiv_id, title, authors, abstract, categories,
                    doi, journal_ref, update_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", papers)
            conn.commit()

    def count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM arxiv_meta").fetchone()[0]

    def exists(self, arxiv_id: str) -> bool:
        with self._conn() as conn:
            r = conn.execute("SELECT 1 FROM arxiv_meta WHERE arxiv_id=?", (arxiv_id,)).fetchone()
            return r is not None


class OaiPmhDownloader(BaseDownloader):
    """OAI-PMH 下载器 — 断点续传、增量更新、优先级队列"""

    source_name = "oai"

    def __init__(self, db_path: str = "", progress_cb=None):
        super().__init__(db_path, progress_cb)
        self.db = ArxivMetaDB(self.db_path)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "HFPClawer/0.2.0 (mailto:lishen@example.com)"})
        self._last_request = 0.0
        self._stats = {"total_fetched": 0, "total_new": 0, "skipped": 0, "errors": 0}

    def _default_db_path(self) -> str:
        from hfpapers.config import get as cfg_get
        base = Path(__file__).resolve().parent.parent.parent
        return str(base / cfg_get("db.path", "data/arxiv_meta.db"))

    def _rate_limit(self):
        elapsed = time.time() - self._last_request
        if elapsed < RATE_LIMIT:
            time.sleep(RATE_LIMIT - elapsed)
        self._last_request = time.time()

    def _oai_request(self, params: dict) -> Optional[ET.Element]:
        for attempt in range(MAX_RETRIES):
            self._rate_limit()
            try:
                resp = self.session.get(OAI_BASE, params=params, timeout=60)
                if resp.status_code == 503:
                    retry_after = int(resp.headers.get("Retry-After", 30))
                    logger.warning(f"  503 限流等待 {retry_after}s...")
                    time.sleep(retry_after)
                    continue
                if resp.status_code != 200:
                    logger.warning(f"  HTTP {resp.status_code}, retry {attempt+1}/{MAX_RETRIES}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_BACKOFF[attempt])
                    continue

                root = ET.fromstring(resp.content)
                error = root.find(".//{http://www.openarchives.org/OAI/2.0/}error")
                if error is not None:
                    code = error.get("code", "")
                    if code == "noRecordsMatch":
                        return None
                    if code == "badResumptionToken":
                        logger.warning("  resumptionToken 失效，重新开始")
                        return None
                    logger.warning(f"  OAI 错误 [{code}]: {error.text}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_BACKOFF[attempt])
                    continue
                return root

            except (requests.RequestException, ET.ParseError) as e:
                logger.warning(f"  请求失败: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF[attempt])
                continue

        logger.error(f"  [{params.get('set', '?')}] 请求最终失败")
        self._stats["errors"] += 1
        return None

    def _parse_record(self, record: ET.Element) -> Optional[tuple]:
        ns = {"oai": "http://www.openarchives.org/OAI/2.0/", "arxiv": "http://arxiv.org/OAI/arXiv/"}
        header = record.find(".//oai:header", ns)
        if header is not None and header.find("oai:status", ns) is not None:
            return None
        metadata = record.find(".//oai:metadata", ns)
        if metadata is None:
            return None
        arxiv = metadata.find("arxiv:arXiv", ns)
        if arxiv is None:
            return None
        arxiv_id_el = arxiv.find("arxiv:id", ns)
        if arxiv_id_el is None or not arxiv_id_el.text:
            return None
        arxiv_id = arxiv_id_el.text.strip()
        if not re.match(r"^\d{4}\.\d{4,5}(?:v\d+)?$", arxiv_id):
            arxiv_id = arxiv_id.split("v")[0]
            if not re.match(r"^\d{4}\.\d{4,5}$", arxiv_id):
                return None

        def el_text(tag: str) -> str:
            el = arxiv.find(f"arxiv:{tag}", ns)
            return (el.text or "").strip()[:500] if el is not None else ""

        title = el_text("title")
        authors = el_text("authors")
        abstract = el_text("abstract")
        categories = el_text("categories")
        doi = ""
        doi_el = arxiv.find("arxiv:doi", ns)
        if doi_el is not None and doi_el.text:
            doi = doi_el.text.strip()
        journal_ref = ""
        jr_el = arxiv.find("arxiv:journal_ref", ns)
        if jr_el is not None and jr_el.text:
            journal_ref = jr_el.text.strip()[:200]
        update_date = ""
        version = arxiv.find("arxiv:version", ns)
        if version is not None:
            date_el = version.find("arxiv:date", ns)
            if date_el is not None and date_el.text:
                update_date = date_el.text[:10]
        if not title:
            return None
        return (arxiv_id, title[:500], authors[:500], abstract[:2000],
                categories, doi, journal_ref, update_date)

    def download_set(self, set_spec: str, from_date: str = "",
                     to_date: str = "", max_pages: int = 0) -> int:
        """下载一个分类的全部/增量记录"""
        new_count = 0
        page = 0
        resumption_token = None

        params = {"verb": "ListRecords", "metadataPrefix": "arXiv", "set": set_spec}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["until"] = to_date

        while not self._interrupted:
            page += 1
            if max_pages > 0 and page > max_pages:
                break

            if resumption_token:
                params = {"verb": "ListRecords", "resumptionToken": resumption_token}

            root = self._oai_request(params)
            if root is None:
                break

            records = root.findall(".//{http://www.openarchives.org/OAI/2.0/}record")
            if not records:
                break

            batch = []
            for record in records:
                parsed = self._parse_record(record)
                if parsed:
                    arxiv_id = parsed[0]
                    if not self.db.exists(arxiv_id):
                        batch.append(parsed)
                    else:
                        self._stats["skipped"] += 1

                    if len(batch) >= BATCH_WRITE:
                        self.db.insert_batch(batch)
                        new_count += len(batch)
                        self._stats["total_new"] += len(batch)
                        batch = []

                    self._stats["total_fetched"] += 1

            if batch:
                self.db.insert_batch(batch)
                new_count += len(batch)
                self._stats["total_new"] += len(batch)

            # 进度上报
            self._update_progress(self._stats["total_fetched"], self._stats["total_new"])

            token_el = root.find(".//{http://www.openarchives.org/OAI/2.0/}resumptionToken")
            if token_el is not None and token_el.text:
                resumption_token = token_el.text
                cursor = int(token_el.get("cursor", 0))
                total = int(token_el.get("completeListSize", 0))
                logger.info(f"  [{set_spec}] page {page}: +{new_count} (cursor: {cursor:,}/{total:,})")
            else:
                logger.info(f"  [{set_spec}] 完成: +{new_count}")
                break

        return new_count

    def run(self, incremental: bool = True, from_date: str = "",
            tier1_only: bool = False, **kwargs) -> int:
        """执行下载

        Args:
            incremental: 增量模式（仅最近1天）
            from_date: 起始日期 YYYY-MM-DD
            tier1_only: 仅下载 Tier 1 核心分类

        Returns:
            新增条数
        """
        self._stats = {"total_fetched": 0, "total_new": 0, "skipped": 0, "errors": 0}

        # 断点续传: 读取上次进度
        state = self.state.get()

        if incremental and not from_date:
            # 增量模式: 从上次完成日期开始
            checksum = state.get("checksum", "")
            if checksum:
                _from, _to = ResumeState.parse_date_range(checksum)
                if _to:
                    from_date = _to
                else:
                    from_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                from_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            logger.info(f"增量模式，从 {from_date} 开始")

        self.state.set_status("running")

        priorities = DOWNLOAD_PRIORITIES
        if tier1_only:
            priorities = priorities[:11]

        total_new = 0
        start_all = time.time()

        for idx, set_spec in enumerate(priorities):
            logger.info(f"[{idx+1}/{len(priorities)}] 📥 {set_spec}")
            set_start = time.time()
            new_count = self.download_set(set_spec, from_date=from_date)
            elapsed = time.time() - set_start
            total_new += new_count

            if new_count > 0:
                rate = new_count / elapsed if elapsed > 0 else 0
                logger.info(f"  → {new_count} 篇 in {elapsed:.1f}s ({rate:.0f}/s)")

            # 检查中断
            if self._interrupted:
                logger.warning("⚠️ 收到中断信号，停止下载")
                break

        # 保存 checksum（日期范围）
        checksum = ResumeState.date_range_to_checksum(from_date)

        all_elapsed = time.time() - start_all
        total_in_db = self.db.count()

        logger.info(f"\n{'='*50}")
        logger.info(f"✅ 下载完成")
        logger.info(f"  新增: {total_new} 篇")
        logger.info(f"  总计: {total_in_db:,} 篇")
        logger.info(f"  耗时: {all_elapsed:.0f}s")

        self.state.mark_done()
        return total_new

    def print_status(self):
        """打印下载状态"""
        from hfpclawer.download.base import logger as base_logger
        state = self.state.get()
        total = self.db.count()

        print(f"\n📊 arXiv OAI-PMH 下载状态")
        print(f"  DB 论文总数: {total:,}")
        print(f"  状态:        {state.get('status', 'unknown')}")
        print(f"  上次更新:    {state.get('last_update', '从未')}")
        print(f"  已获取:      {state.get('total_fetched', 0):,}")
        print(f"  本次新增:    {state.get('total_new', 0):,}")
        print(f"  checksum:    {state.get('checksum', 'N/A')}")
        print(f"  DB 路径: {self.db_path}")
