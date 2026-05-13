# ─── 异步搜索调度器 ──────────────────────────
# hfpapers/search_queue.py
# 基于 asyncio PriorityQueue 的并发搜索调度器

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from hfpapers.searcher_registry import (
    SearchResult, BaseSearcher, get_available, init_registry,
)

logger = logging.getLogger("hfpapers.search_queue")

# ════════════════════════════════════════════
# 队列任务模型
# ════════════════════════════════════════════


@dataclass(order=True)
class SearchTask:
    """搜索任务（按优先级排序）"""
    priority: int = 5               # 小=优先执行
    query: str = ""                 # 必须有默认值（因为 priority 有默认值）
    category: str = ""
    limit: int = 30
    max_retries: int = 2
    retry_count: int = 0
    created_at: float = 0.0


# ════════════════════════════════════════════
# 统一搜索验证器
# ════════════════════════════════════════════

import re
import requests

_ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(?:v\d+)?$")

def verify_arxiv_title(aid: str, session: requests.Session = None) -> str:
    """验证 arXiv ID 并获取真实标题

    用 arXiv 缩写 URI (export.arxiv.org) 替代完整页面抓取，更快更可靠。

    Returns:
        真实标题，或空字符串（失败）
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
        from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
        import warnings
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(resp.text, "lxml")
        tag = soup.find("title")
        if tag:
            title = tag.get_text(strip=True)
            # arXiv API 返回格式: "title: FNO for Parametric PDEs"
            title = re.sub(r"^title:\s*", "", title, flags=re.IGNORECASE).strip()
            return title[:200]
        return ""
    except Exception:
        return ""
    finally:
        if close_session:
            session.close()


# ════════════════════════════════════════════
# 异步搜索调度器
# ════════════════════════════════════════════


class SearchDispatcher:
    """异步搜索调度器

    用法:
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

        # 确保搜索器已注册
        init_registry()

    def add_task(self, query: str, category: str = "", limit: int = 30, priority: int = 5):
        task = SearchTask(
            priority=priority,
            query=query,
            category=category,
            limit=limit,
        )
        self.queue.put_nowait(task)
        logger.debug(f"入队: [{priority}] {category}:{query}")

    def add_tasks_from_config(self, queries_config: list[dict]):
        """从配置文件批量添加任务"""
        for q in queries_config:
            self.add_task(
                query=q.get("query", ""),
                category=q.get("category", "unknown"),
                limit=q.get("limit", 30),
                priority=q.get("priority", 5),
            )
        logger.info(f"已加载 {len(queries_config)} 个搜索任务")

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": "Mozilla/5.0"})
        return self._session

    async def _search_one_source(self, searcher: BaseSearcher, task: SearchTask) -> list[SearchResult]:
        """用单个搜索器搜索"""
        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, searcher.search_sync, task.query, task.limit, task.category,
            )
            return results
        except Exception as e:
            logger.warning(f"[{searcher.name}] {task.query} 失败: {e}")
            return []

    async def _process_task(self, task: SearchTask):
        """处理一个搜索任务（遍历所有可用搜索器，第一个成功即返回）"""
        async with self.sem:
            searchers = get_available()
            for searcher in searchers:
                results = await self._search_one_source(searcher, task)
                if results:
                    # 去重 + 验证
                    new_results = self._dedup_and_verify(results)
                    if new_results:
                        self.results.extend(new_results)
                        logger.info(
                            f"  ✅ [{task.category}] {searcher.name}: "
                            f"{len(results)}->{len(new_results)} 篇新论文"
                        )
                        return
                else:
                    logger.debug(f"  [{task.category}] {searcher.name}: 0 结果，尝试下一源")

            # 所有源都失败时重试
            if task.retry_count < task.max_retries:
                task.retry_count += 1
                logger.debug(f"  [{task.category}] 所有源失败，重试 {task.retry_count}/{task.max_retries}")
                await asyncio.sleep(2 ** task.retry_count)  # 指数退避
                self.queue.put_nowait(task)

    def _dedup_and_verify(self, results: list[SearchResult]) -> list[SearchResult]:
        """去重 + arXiv 标题验证"""
        verified = []

        for r in results:
            aid = r.arxiv_id
            if not aid or not _ARXIV_ID_RE.match(aid):
                continue
            if aid in self._seen_ids:
                continue

            # arXiv 验证
            if self._verify_enabled:
                real_title = verify_arxiv_title(aid, self.session)
                if real_title and r.title:
                    # 检查标题相似度
                    sim = _title_similarity(r.title, real_title)
                    from hfpapers.config import get as cfg_get
                    min_sim = cfg_get("classification.title_similarity_min", 0.40)
                    if sim < min_sim:
                        logger.warning(f"  ⚠️ {aid} ID错配: sim={sim:.2f} (hf='{r.title[:40]}' vs arxiv='{real_title[:40]}')")
                        continue
                    r.title = real_title

            self._seen_ids.add(aid)
            verified.append(r)

        return verified

    async def run(self) -> list[SearchResult]:
        """运行调度器，直到队列清空"""
        total = self.queue.qsize()
        logger.info(f"🚀 启动搜索调度器: {total} 个任务, {self.max_workers} 并发")

        workers = []
        for _ in range(min(self.max_workers, total)):
            worker = asyncio.create_task(self._worker_loop())
            workers.append(worker)

        await asyncio.gather(*workers)

        if self._session:
            self._session.close()
            self._session = None

        logger.info(f"✅ 搜索完成: {len(self.results)} 篇新论文 (来自 {total} 个查询)")
        return self.results

    async def _worker_loop(self):
        """Worker 循环 —— 从队列取任务并处理"""
        while True:
            try:
                task = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                return

            try:
                await self._process_task(task)
            except Exception as e:
                logger.error(f"任务处理异常: {e}")
            finally:
                self.queue.task_done()


# ════════════════════════════════════════════
# 标题相似度（复用 evolved.py 的逻辑）
# ════════════════════════════════════════════


def _title_similarity(t1: str, t2: str) -> float:
    """三字母组 Jaccard 相似度"""
    t1, t2 = t1.lower().strip(), t2.lower().strip()
    t1 = re.sub(r"[^a-z0-9\s]", "", t1)
    t2 = re.sub(r"[^a-z0-9\s]", "", t2)

    def trigrams(s: str) -> set[str]:
        return {s[i:i+3] for i in range(len(s)-2)}

    s1, s2 = trigrams(t1), trigrams(t2)
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)
