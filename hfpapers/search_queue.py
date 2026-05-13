#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ─── Async Search Dispatcher ──────────────────────────
# hfpapers/search_queue.py
# asyncio PriorityQueue-based concurrent search dispatcher

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

import requests

from hfpapers.searcher_registry import (
    BaseSearcher,
    SearchResult,
    get_available,
    init_registry,
)

logger = logging.getLogger("hfpapers.search_queue")

# ════════════════════════════════════════════
# Queue Task Model
# ════════════════════════════════════════════


@dataclass(order=True)
class SearchTask:
    """Search task (sorted by priority)"""
    priority: int = 5               # Lower = higher priority
    query: str = ""                 # Must have default (due to priority default)
    category: str = ""
    limit: int = 30
    max_retries: int = 2
    retry_count: int = 0
    created_at: float = 0.0


# ════════════════════════════════════════════
# Unified Search Validator
# ════════════════════════════════════════════


_ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(?:v\d+)?$")

def verify_arxiv_title(aid: str, session: requests.Session = None) -> str:
    """Verify arXiv ID and fetch real title

    Uses arXiv export API (export.arxiv.org) instead of full page fetch — faster and more reliable.

    Returns:
        Real title, or empty string (on failure)
    """
    close_session = False
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        close_session = True
    try:
        resp = session.get(
            f"http://export.arxiv.org/api/query?id_list={aid}&max_results=1",
            timeout=15,
        )
        if resp.status_code != 200:
            return ""
        import warnings

        from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(resp.text, "lxml")
        tag = soup.find("title")
        if tag:
            title = tag.get_text(strip=True)
            # arXiv API returns: "title: FNO for Parametric PDEs"
            title = re.sub(r"^title:\s*", "", title, flags=re.IGNORECASE).strip()
            return title[:200]
        return ""
    except Exception:
        return ""
    finally:
        if close_session:
            session.close()


# ════════════════════════════════════════════
# Async search dispatcher
# ════════════════════════════════════════════


class SearchDispatcher:
    """Async search scheduler

    Usage:
        dispatcher = SearchDispatcher(max_workers=5)
        dispatcher.add_task("neural operator", category="FNO")
        dispatcher.add_task("physics informed", category="PINN")
        results = await dispatcher.run()
    """

    def __init__(self, max_workers: int = 5):
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.results: list[SearchResult] = []
        self._seen_ids: set[str] = set()
        self.max_workers = max_workers
        self.sem = asyncio.Semaphore(max_workers)
        self._session: Optional[requests.Session] = None
        self._verify_enabled = True

        # Ensure searchers are registered
        init_registry()

    def add_task(self, query: str, category: str = "", limit: int = 30, priority: int = 5):
        task = SearchTask(
            priority=priority,
            query=query,
            category=category,
            limit=limit,
        )
        self.queue.put_nowait(task)
        logger.debug(f"Enqueued: [{priority}] {category}:{query}")

    def add_tasks_from_config(self, queries_config: list[dict]):
        """Batch add tasks from config"""
        for q in queries_config:
            self.add_task(
                query=q.get("query", ""),
                category=q.get("category", "unknown"),
                limit=q.get("limit", 30),
                priority=q.get("priority", 5),
            )
        logger.info(f"Loaded {len(queries_config)} search tasks")

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": "Mozilla/5.0"})
        return self._session

    async def _search_one_source(self, searcher: BaseSearcher, task: SearchTask) -> list[SearchResult]:
        """Search with a single searcher"""
        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, searcher.search_sync, task.query, task.limit, task.category,
            )
            return results
        except Exception as e:
            logger.warning(f"[{searcher.name}] {task.query} failed: {e}")
            return []

    async def _process_task(self, task: SearchTask):
        """Process a search task (iterate through all available searchers, return on first success)"""
        async with self.sem:
            searchers = get_available()
            for searcher in searchers:
                results = await self._search_one_source(searcher, task)
                if results:
                    # Deduplication + verification
                    new_results = self._dedup_and_verify(results)
                    if new_results:
                        self.results.extend(new_results)
                        logger.info(
                            f"  ✅ [{task.category}] {searcher.name}: "
                            f"{len(results)}->{len(new_results)} new papers"
                        )
                        return
                else:
                    logger.debug(f"  [{task.category}] {searcher.name}: 0 results, trying next source")

            # Retry when all sources fail
            if task.retry_count < task.max_retries:
                task.retry_count += 1
                logger.debug(f"  [{task.category}] All sources failed, retry {task.retry_count}/{task.max_retries}")
                await asyncio.sleep(2 ** task.retry_count)  # Exponential backoff
                self.queue.put_nowait(task)

    def _dedup_and_verify(self, results: list[SearchResult]) -> list[SearchResult]:
        """Dedup + arXiv title verification"""
        verified = []

        for r in results:
            aid = r.arxiv_id
            if not aid or not _ARXIV_ID_RE.match(aid):
                continue
            if aid in self._seen_ids:
                continue

            # arXiv verification
            if self._verify_enabled:
                real_title = verify_arxiv_title(aid, self.session)
                if real_title and r.title:
                    # Check title similarity
                    sim = _title_similarity(r.title, real_title)
                    from hfpapers.config import get as cfg_get
                    min_sim = cfg_get("classification.title_similarity_min", 0.40)
                    if sim < min_sim:
                        logger.warning(f"  ⚠️ {aid} ID mismatch: sim={sim:.2f} (hf='{r.title[:40]}' vs arxiv='{real_title[:40]}')")
                        continue
                    r.title = real_title

            self._seen_ids.add(aid)
            verified.append(r)

        return verified

    async def run(self) -> list[SearchResult]:
        """Run dispatcher until queue is empty"""
        total = self.queue.qsize()
        logger.info(f"🚀 Starting search dispatcher: {total} tasks, {self.max_workers} concurrent")

        workers = []
        for _ in range(min(self.max_workers, total)):
            worker = asyncio.create_task(self._worker_loop())
            workers.append(worker)

        await asyncio.gather(*workers)

        if self._session:
            self._session.close()
            self._session = None

        logger.info(f"✅ Search complete: {len(self.results)} new papers (from {total} queries)")
        return self.results

    async def _worker_loop(self):
        """Worker loop — fetch tasks from queue and process"""
        while True:
            try:
                task = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                return

            try:
                await self._process_task(task)
            except Exception as e:
                logger.error(f"Task processing exception: {e}")
            finally:
                self.queue.task_done()


# ════════════════════════════════════════════
# Title Similarity (reuses evolved.py logic)
# ════════════════════════════════════════════


def _title_similarity(t1: str, t2: str) -> float:
    """Trigram Jaccard similarity"""
    t1, t2 = t1.lower().strip(), t2.lower().strip()
    t1 = re.sub(r"[^a-z0-9\s]", "", t1)
    t2 = re.sub(r"[^a-z0-9\s]", "", t2)

    def trigrams(s: str) -> set[str]:
        return {s[i:i+3] for i in range(len(s)-2)}

    s1, s2 = trigrams(t1), trigrams(t2)
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)
