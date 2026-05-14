#!/usr/bin/env python3
"""
download_queue.py — Batch download queue backed by paper_store

Features:
  - Pull papers from paper_store by priority tiers
  - Mark download/convert status in DB (not just file existence)
  - aiohttp concurrent download → pymupdf4llm MD → optional wiki sync
  - Resume-proof: tracks which papers are done/pending/failed
  - Progress callback for CLI / cron

Architecture:
  paper_store.papers (download_status/convert_status/wiki_synced)
       │
       ▼
  DownloadQueue.pull_batch() → filter pending papers
       │
       ▼
  AsyncPdfDownloader.download_batch() → aiohttp 8 concurrent
       │
       ▼
  DownloadQueue._mark_done() → update DB status
       │
       ▼
  DownloadQueue._convert_and_sync() → pymupdf4llm → wiki

Usage:
    queue = DownloadQueue()
    summary = queue.batch_download(batch_size=50, to_wiki=True)
    # → {"downloaded": 45, "converted": 45, "failed": 2, "skipped": 3}
"""

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from hfpapers.config import get as cfg_get
from hfpapers.logger import get_audit, init_logging, record_event
from hfpapers.paper_store import get_store

logger = logging.getLogger("hfpapers.download_queue")

BASE_DIR = Path(__file__).parent.parent
PDF_DIR = BASE_DIR / cfg_get("paths.pdf_dir", "data/pdfs")
MD_DIR = BASE_DIR / cfg_get("paths.md_dir", "data/md_extracts")
WIKI_DIR = Path.home() / "wiki" / "raw" / "papers"

os.makedirs(PDF_DIR, exist_ok=True)
os.makedirs(MD_DIR, exist_ok=True)


# ─── DB Schema Migration ─────────────────────────────────

MIGRATE_SQL = """
ALTER TABLE papers ADD COLUMN download_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE papers ADD COLUMN convert_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE papers ADD COLUMN wiki_synced INTEGER NOT NULL DEFAULT 0;
ALTER TABLE papers ADD COLUMN failed_reason TEXT NOT NULL DEFAULT '';
    ALTER TABLE papers ADD COLUMN converted_at TEXT DEFAULT '';
    ALTER TABLE papers ADD COLUMN conversion_version TEXT DEFAULT 'hfpapers-dq-1.0';
"""

MIGRATE_CHECK_SQL = """
SELECT COUNT(*) FROM pragma_table_info('papers')
WHERE name = 'converted_at'
"""


def ensure_migration():
    """Add status columns if not present (idempotent)"""
    store = get_store()
    with store._lock, store._conn() as conn:
        has_col = conn.execute(MIGRATE_CHECK_SQL).fetchone()[0]
        if has_col:
            return  # Already migrated

        logger.info("📦 Running papers table migration (add status columns)...")
        for stmt in MIGRATE_SQL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as e:
                    if "duplicate column" in str(e).lower():
                        continue
                    raise
        conn.commit()
        logger.info("✅ Migration complete")

        # Backfill from existing files
        _backfill_from_files(conn)


def _backfill_from_files(conn):
    """Scan existing PDF/MD/wiki files and update status"""
    # Mark downloaded
    done_ids = set(f.stem for f in PDF_DIR.glob("*.pdf"))
    if done_ids:
        conn.executemany(
            "UPDATE papers SET download_status='done' WHERE download_status='pending' "
            "AND sf_id IN (SELECT p.sf_id FROM papers p "
            "JOIN identifiers i ON p.sf_id = i.sf_id WHERE i.id_type='arxiv' AND i.id_value=?)",
            [(aid,) for aid in done_ids],
        )

    # Mark converted
    converted_ids = set(f.stem for f in MD_DIR.glob("*.md"))
    if converted_ids:
        conn.executemany(
            "UPDATE papers SET convert_status='done' WHERE convert_status='pending' "
            "AND sf_id IN (SELECT p.sf_id FROM papers p "
            "JOIN identifiers i ON p.sf_id = i.sf_id WHERE i.id_type='arxiv' AND i.id_value=?)",
            [(aid,) for aid in converted_ids],
        )

    # Mark wiki synced
    wiki_ids = set(f.stem for f in WIKI_DIR.glob("*.md"))
    if wiki_ids:
        conn.executemany(
            "UPDATE papers SET wiki_synced=1 WHERE wiki_synced=0 "
            "AND sf_id IN (SELECT p.sf_id FROM papers p "
            "JOIN identifiers i ON p.sf_id = i.sf_id WHERE i.id_type='arxiv' AND i.id_value=?)",
            [(aid,) for aid in wiki_ids],
        )

    conn.commit()
    logger.info(
        f"📊 Backfill: {len(done_ids)} downloaded, "
        f"{len(converted_ids)} converted, {len(wiki_ids)} wiki-synced"
    )


# ─── Queue Data ──────────────────────────────────────────


@dataclass
class BatchSummary:
    downloaded: int = 0
    converted: int = 0
    failed: int = 0
    skipped: int = 0
    wiki_synced: int = 0
    total: int = 0
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    @property
    def summary_line(self) -> str:
        return (
            f"⬇️ {self.downloaded} DL | 📝 {self.converted} MD | "
            f"📋 {self.wiki_synced} wiki | ❌ {self.failed} fail | "
            f"⏭️ {self.skipped} skip (of {self.total})"
        )


# ─── DownloadQueue ────────────────────────────────────────


class DownloadQueue:
    """Priority download queue backed by paper_store status columns"""

    def __init__(self, max_concurrent: int = 8, progress_cb: Callable = None):
        ensure_migration()
        self.store = get_store()
        self.max_concurrent = max_concurrent
        self.progress_cb = progress_cb or (lambda r: None)
        self.summary: Optional[BatchSummary] = None
        self._arxiv_ids: dict[str, int] = {}  # arxiv_id → paper sf_id

    # ── Pull ────────────────────────────────────────────

    def pull_batch(self, batch_size: int = 50, priority: str = "P0") -> list[dict]:
        """Pull pending papers from paper_store

        Priority tiers:
            P0: relevance >= 60 (high value, immediate)
            P1: relevance >= 30 and < 60
            P2: all remaining pending
        """
        with self.store._conn() as conn:
            if priority == "P0":
                rows = conn.execute(
                    """SELECT p.sf_id, p.title, p.abstract, p.relevance, i.id_value as arxiv_id
                       FROM papers p
                       JOIN identifiers i ON p.sf_id = i.sf_id AND i.id_type='arxiv'
                       WHERE p.download_status='pending' AND p.relevance >= 60
                       ORDER BY p.relevance DESC
                       LIMIT ?""",
                    (batch_size,),
                ).fetchall()
            elif priority == "P1":
                rows = conn.execute(
                    """SELECT p.sf_id, p.title, p.abstract, p.relevance, i.id_value as arxiv_id
                       FROM papers p
                       JOIN identifiers i ON p.sf_id = i.sf_id AND i.id_type='arxiv'
                       WHERE p.download_status='pending' AND p.relevance >= 30 AND p.relevance < 60
                       ORDER BY p.relevance DESC
                       LIMIT ?""",
                    (batch_size,),
                ).fetchall()
            else:  # P2 — all remaining
                rows = conn.execute(
                    """SELECT p.sf_id, p.title, p.abstract, p.relevance, i.id_value as arxiv_id
                       FROM papers p
                       JOIN identifiers i ON p.sf_id = i.sf_id AND i.id_type='arxiv'
                       WHERE p.download_status='pending'
                       ORDER BY p.relevance DESC
                       LIMIT ?""",
                    (batch_size,),
                ).fetchall()

            papers = []
            for r in rows:
                papers.append(
                    {
                        "arxiv_id": r["arxiv_id"],
                        "sf_id": r["sf_id"],
                        "title": r["title"],
                        "abstract": r["abstract"],
                        "relevance": r["relevance"],
                    }
                )
                self._arxiv_ids[r["arxiv_id"]] = r["sf_id"]

        return papers

    def count_pending(self) -> dict:
        """Count papers by download status"""
        with self.store._conn() as conn:
            rows = conn.execute(
                "SELECT download_status, COUNT(*) FROM papers GROUP BY download_status"
            ).fetchall()
            counts = {"pending": 0, "done": 0, "failed": 0, "downloading": 0}
            for r in rows:
                counts[r[0]] = r[1]
            return counts

    # ── Update Status ───────────────────────────────────

    def _mark_status(self, arxiv_id: str, field: str, value: str):
        """Update a status field for a paper"""
        sf_id = self._arxiv_ids.get(arxiv_id)
        if sf_id is None:
            # Look it up
            paper = self.store.get_paper_by_identifier("arxiv", arxiv_id)
            if paper is None:
                return
            sf_id = paper.sf_id
            self._arxiv_ids[arxiv_id] = sf_id

        with self.store._lock, self.store._conn() as conn:
            conn.execute(
                f"UPDATE papers SET {field}=?, updated_at=datetime('now') WHERE sf_id=?",
                (value, sf_id),
            )

    def _mark_failed(self, arxiv_id: str, reason: str):
        sf_id = self._arxiv_ids.get(arxiv_id, 0)
        with self.store._lock, self.store._conn() as conn:
            conn.execute(
                "UPDATE papers SET download_status='failed', failed_reason=?, "
                "updated_at=datetime('now') WHERE sf_id=?",
                (reason[:500], sf_id),
            )

    # ── Full Batch Download ─────────────────────────────

    def batch_download(
        self,
        batch_size: int = 50,
        priority: str = "P0",
        skip_convert: bool = False,
        to_wiki: bool = True,
        max_retries: int = 2,
    ) -> BatchSummary:
        """Complete batch pipeline: pull → download → convert → wiki sync

        Converts MD files concurrently using ThreadPoolExecutor (up to 4 workers).
        Returns BatchSummary with per-step counts.
        """
        init_logging()
        self.summary = BatchSummary()
        batch_id = datetime.now().strftime("b%Y%m%d_%H%M%S")
        audit = get_audit()
        import concurrent.futures

        papers = self.pull_batch(batch_size=batch_size, priority=priority)
        if not papers:
            logger.info("📭 No pending papers in queue")
            return self.summary

        self.summary.total = len(papers)
        logger.info(f"📥 Batch {batch_id}: {len(papers)} papers from priority={priority}")
        audit.record(
            event="batch_start",
            batch_id=batch_id,
            phase="batch",
            meta={"priority": priority, "count": len(papers)},
        )

        # Step 1: Mark all as downloading
        for p in papers:
            self._mark_status(p["arxiv_id"], "download_status", "downloading")
            audit.record(
                arxiv_id=p["arxiv_id"],
                event="download_start",
                batch_id=batch_id,
                phase="download",
                meta={"title": p["title"][:80], "priority": priority},
            )

        # Step 2: Download PDFs via AsyncPdfDownloader
        dl_start = time.time()
        results = self._run_async_download(papers, max_retries)

        # Step 3: Process results — convert concurrently
        convert_tasks = []
        for r in results:
            aid = r["arxiv_id"]
            if r["success"]:
                dl_elapsed = time.time() - dl_start
                self._mark_status(aid, "download_status", "done")
                audit.record(
                    arxiv_id=aid,
                    event="download_done",
                    batch_id=batch_id,
                    phase="download",
                    status="done",
                    duration_s=dl_elapsed,
                )
                self.summary.downloaded += 1

                if not skip_convert and r.get("pdf_path"):
                    title = next((p["title"] for p in papers if p["arxiv_id"] == aid), "")
                    convert_tasks.append((aid, r["pdf_path"], title))
                else:
                    # Progress callback for skip
                    try:
                        self.progress_cb({"arxiv_id": aid, "summary": self.summary})
                    except Exception:
                        pass
            else:
                self._mark_failed(aid, r.get("error", "unknown"))
                self.summary.failed += 1
                self.summary.errors.append(f"{aid}: {r.get('error', 'unknown')}")
                audit.record(
                    arxiv_id=aid,
                    event="download_failed",
                    batch_id=batch_id,
                    phase="download",
                    status="failed",
                    meta={"error": r.get("error", "unknown")[:200]},
                )
                try:
                    self.progress_cb({"arxiv_id": aid, "summary": self.summary})
                except Exception:
                    pass

        # Step 3a: Concurrent conversion (up to 4 workers)
        if convert_tasks:
            conv_start = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                future_map = {}
                for aid, pdf_path, title in convert_tasks:
                    fut = pool.submit(
                        self._convert_one,
                        aid,
                        pdf_path,
                        title=title,
                        to_wiki=to_wiki,
                        batch_id=batch_id,
                    )
                    future_map[fut] = aid

                for fut in concurrent.futures.as_completed(future_map):
                    aid = future_map[fut]
                    conv_elapsed = time.time() - conv_start
                    try:
                        ok = fut.result()
                        if ok:
                            self.summary.converted += 1
                            audit.record(
                                arxiv_id=aid,
                                event="convert_done",
                                batch_id=batch_id,
                                phase="convert",
                                status="done",
                                duration_s=conv_elapsed,
                            )
                        else:
                            self.summary.failed += 1
                            audit.record(
                                arxiv_id=aid,
                                event="convert_failed",
                                batch_id=batch_id,
                                phase="convert",
                                status="failed",
                                duration_s=conv_elapsed,
                            )
                    except Exception as e:
                        self.summary.failed += 1
                        self.summary.errors.append(f"{aid} convert: {e}")
                        audit.record(
                            arxiv_id=aid,
                            event="convert_failed",
                            batch_id=batch_id,
                            phase="convert",
                            status="failed",
                            duration_s=conv_elapsed,
                            meta={"error": str(e)[:200]},
                        )

                    # Progress callback
                    try:
                        self.progress_cb({"arxiv_id": aid, "summary": self.summary})
                    except Exception:
                        pass

        total_elapsed = time.time() - dl_start
        audit.record(
            event="batch_done",
            batch_id=batch_id,
            phase="batch",
            status="done",
            duration_s=total_elapsed,
            meta={"summary": self.summary.summary_line},
        )

        logger.info(f"✅ Batch {batch_id} complete: {self.summary.summary_line}")
        return self.summary

    def _run_async_download(self, papers: list[dict], max_retries: int) -> list[dict]:
        """Run AsyncPdfDownloader in a fresh event loop (PDF download only, no MD conversion)"""
        from hfpapers.pdf_downloader_async import AsyncPdfDownloader

        async_dl = AsyncPdfDownloader(
            max_concurrent=min(self.max_concurrent, len(papers)),
            pdf_dir=str(PDF_DIR),
            md_dir=str(MD_DIR),
            progress_cb=lambda r: logger.info(
                f"  {'✅' if r['success'] else '❌'} {r['arxiv_id']}"
            ),
        )

        # Disable internal MD conversion — we do it externally with version metadata
        async def _noop_md(*a, **kw):
            return None

        async_dl._convert_to_md = _noop_md

        papers_dict = [
            {
                "arxiv_id": p["arxiv_id"],
                "title": p["title"],
                "abstract": p.get("abstract", ""),
            }
            for p in papers
        ]

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(async_dl.download_batch(papers_dict))
        finally:
            loop.close()

    CONVERSION_VERSION = "hfpapers-dq-1.0"

    def _build_md_header(self, arxiv_id: str, title: str = "") -> str:
        """Build YAML frontmatter with version metadata"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_only = datetime.now().strftime("%Y-%m-%d")
        header = {
            "arxiv_id": arxiv_id,
            "title": title or arxiv_id,
            "source": "arXiv PDF",
            "converted_at": now,
            "conversion_date": date_only,
            "conversion_version": self.CONVERSION_VERSION,
            "conversion_tool": "pymupdf4llm",
        }
        return "---\n" + json.dumps(header, ensure_ascii=False, indent=2) + "\n---\n\n"

    def _mark_converted(self, arxiv_id: str):
        """Mark conversion complete with timestamp"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sf_id = self._arxiv_ids.get(arxiv_id)
        if sf_id:
            with self.store._lock, self.store._conn() as conn:
                conn.execute(
                    "UPDATE papers SET convert_status='done', converted_at=?, "
                    "conversion_version=?, updated_at=datetime('now') WHERE sf_id=?",
                    (now, self.CONVERSION_VERSION, sf_id),
                )

    def _convert_one(
        self,
        arxiv_id: str,
        pdf_path: str,
        title: str = "",
        to_wiki: bool = True,
        batch_id: str = "",
    ) -> bool:
        """Convert a single PDF to MD, optionally sync to wiki"""
        try:
            import pymupdf4llm
        except ImportError:
            logger.warning("pymupdf4llm unavailable, skipping MD conversion")
            self._mark_status(arxiv_id, "convert_status", "failed")
            return False

        md_path = MD_DIR / f"{arxiv_id}.md"
        try:
            md_text = pymupdf4llm.to_markdown(pdf_path)
            header = self._build_md_header(arxiv_id, title=title)
            with open(md_path, "w") as f:
                f.write(header + md_text)
            self._mark_converted(arxiv_id)
            logger.info(f"  📝 MD: {arxiv_id}")

            # Wiki sync
            if to_wiki:
                WIKI_DIR.mkdir(parents=True, exist_ok=True)
                wiki_path = WIKI_DIR / f"{arxiv_id}.md"
                shutil.copy2(str(md_path), str(wiki_path))
                self.summary.wiki_synced += 1
                self._mark_status(arxiv_id, "wiki_synced", "1")
                if batch_id:
                    record_event(
                        arxiv_id=arxiv_id,
                        event="wiki_sync",
                        batch_id=batch_id,
                        phase="wiki_sync",
                        status="done",
                        meta={"file": str(wiki_path)},
                    )
                logger.info(f"  📋 Wiki: {arxiv_id}")

            return True
        except Exception as e:
            logger.warning(f"  ❌ Convert failed {arxiv_id}: {e}")
            self._mark_status(arxiv_id, "convert_status", "failed")
            self._mark_status(arxiv_id, "failed_reason", str(e)[:500])
            if batch_id:
                record_event(
                    arxiv_id=arxiv_id,
                    event="convert_failed",
                    batch_id=batch_id,
                    phase="convert",
                    status="failed",
                    meta={"error": str(e)[:200]},
                )
            return False


# ─── CLI-friendly interface ──────────────────────────────


def batch_download_cli(
    limit: int = 50,
    priority: str = "P0",
    skip_convert: bool = False,
    to_wiki: bool = True,
    max_retries: int = 2,
) -> BatchSummary:
    """CLI entry point for batch download"""
    from hfpapers.hardware import HardwareProbe

    hw = HardwareProbe()
    max_conc = min(8, limit)
    logger.info(f"🔧 {hw.summary()}, max_concurrent={max_conc}")

    queue = DownloadQueue(max_concurrent=max_conc)
    summary = queue.batch_download(
        batch_size=limit,
        priority=priority,
        skip_convert=skip_convert,
        to_wiki=to_wiki,
        max_retries=max_retries,
    )
    return summary
