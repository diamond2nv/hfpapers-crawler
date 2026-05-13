# ─── 统一搜索注册表 ──────────────────────────
# hfpapers/searcher_registry.py
# 所有 Searcher 在此注册，支持同步/异步两种调用方式

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger("hfpapers.searcher_registry")

# ════════════════════════════════════════════
# 搜索适配器接口
# ════════════════════════════════════════════


@dataclass
class SearchResult:
    """统一搜索结果"""
    arxiv_id: str
    title: str
    abstract: str
    source: str               # "hf_cli" | "arxiv_local" | "arxiv_api" | "openreview" | "pwc_api"
    source_category: str = ""
    source_url: str = ""
    code_url: str = ""
    venue: str = ""
    doi: str = ""
    authors: str = ""
    score: float = 0.0
    confidence: float = 0.3


class BaseSearcher(ABC):
    """搜索器基类 — 必须实现 search_sync，search_async 可选"""
    
    name: str = ""
    
    @abstractmethod
    def search_sync(self, query: str, limit: int = 30, category: str = "") -> list[SearchResult]:
        """同步搜索（必须实现）"""
        ...
    
    async def search_async(self, query: str, limit: int = 30, category: str = "") -> list[SearchResult]:
        """异步搜索（默认用线程池执行同步版本）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.search_sync, query, limit, category,
        )
    
    @property
    def priority(self) -> int:
        """搜索优先级（小=优先），默认 100"""
        return 100
    
    def is_available(self) -> bool:
        """是否可用（检查 API key / 本地数据）"""
        return True


# ════════════════════════════════════════════
# 注册表
# ════════════════════════════════════════════

_searchers: dict[str, BaseSearcher] = {}


def register(searcher: BaseSearcher):
    """注册一个搜索器"""
    if not searcher.name:
        raise ValueError("Searcher must have a name")
    _searchers[searcher.name] = searcher
    logger.debug(f"注册搜索器: {searcher.name}")


def get(name: str) -> Optional[BaseSearcher]:
    return _searchers.get(name)


def get_all() -> dict[str, BaseSearcher]:
    return dict(_searchers)


def get_available() -> list[BaseSearcher]:
    """返回所有可用的搜索器（按优先级排序）"""
    available = [s for s in _searchers.values() if s.is_available()]
    available.sort(key=lambda s: s.priority)
    return available


def get_names() -> list[str]:
    return list(_searchers.keys())


# ════════════════════════════════════════════
# 将旧式搜索适配到注册表
# ════════════════════════════════════════════


class HfCliSearcher(BaseSearcher):
    name = "hf_cli"
    
    def search_sync(self, query: str, limit: int = 30, category: str = "") -> list[SearchResult]:
        import json
        import subprocess
        import re
        
        results: list[SearchResult] = []
        try:
            output = subprocess.run(
                ["hf", "papers", "search", query, "--json", "--limit", str(limit)],
                capture_output=True, text=True, timeout=60,
            )
            if output.returncode != 0:
                return results
            data = json.loads(output.stdout)
        except Exception as e:
            logger.debug(f"[hf_cli] {query} 失败: {e}")
            return results
        
        arxiv_id_re = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")
        for pd in data:
            aid = pd.get("id", "")
            if not aid or not arxiv_id_re.match(aid):
                continue
            results.append(SearchResult(
                arxiv_id=aid,
                title=pd.get("title", ""),
                abstract=pd.get("summary", ""),
                source="hf_cli",
                source_url=f"https://huggingface.co/papers?q={query}",
                source_category=category,
            ))
        logger.info(f"  [hf_cli] {query}: {len(results)} 篇")
        return results


class ArxivLocalSearcher(BaseSearcher):
    name = "arxiv_local"
    
    @property
    def priority(self) -> int:
        return 1  # 最高优先级（0 网络开销, 毫秒级）
    
    def is_available(self) -> bool:
        try:
            from hfpapers.arxiv_search import ArxivLocalSearch
            s = ArxivLocalSearch()
            return s.count() > 100
        except Exception:
            return False
    
    def search_sync(self, query: str, limit: int = 100, category: str = "") -> list[SearchResult]:
        from hfpapers.arxiv_search import ArxivLocalSearch
        engine = ArxivLocalSearch()
        raw = engine.search(query=query, limit=limit, year_from=2017, sort="date")
        results = []
        for r in raw:
            results.append(SearchResult(
                arxiv_id=r["arxiv_id"],
                title=r["title"],
                abstract=r["abstract"],
                source="arxiv_local",
                source_url=f"https://arxiv.org/abs/{r['arxiv_id']}",
                source_category=category,
                doi=r.get("doi", ""),
                venue=r.get("journal_ref", ""),
                authors=r.get("authors", ""),
                confidence=0.9 if r.get("doi") and r.get("journal_ref") else (0.6 if r.get("doi") else 0.3),
            ))
        return results


class ArxivApiSearcher(BaseSearcher):
    name = "arxiv_api"
    
    def search_sync(self, query: str, limit: int = 30, category: str = "") -> list[SearchResult]:
        import re
        import requests
        from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
        import warnings
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        
        results: list[SearchResult] = []
        arxiv_id_re = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")
        try:
            resp = requests.get(
                "http://export.arxiv.org/api/query",
                params={
                    "search_query": f"all:{query}",
                    "max_results": limit,
                    "sortBy": "relevance",
                    "sortOrder": "descending",
                },
                timeout=30,
            )
            if resp.status_code != 200:
                return results
            soup = BeautifulSoup(resp.text, "lxml")
            for entry in soup.find_all("entry"):
                aid_tag = entry.find("id")
                if not aid_tag:
                    continue
                match = arxiv_id_re.search(aid_tag.text)
                if not match:
                    continue
                arxiv_id = match.group(1)
                title_tag = entry.find("title")
                abstract_tag = entry.find("summary")
                results.append(SearchResult(
                    arxiv_id=arxiv_id,
                    title=title_tag.text.strip()[:200] if title_tag else "",
                    abstract=abstract_tag.text.strip()[:500] if abstract_tag else "",
                    source="arxiv_api",
                    source_url=f"https://arxiv.org/abs/{arxiv_id}",
                    source_category=category,
                ))
        except Exception as e:
            logger.warning(f"  [arxiv_api] 搜索失败: {e}")
        return results


class OpenReviewSearcher(BaseSearcher):
    name = "openreview"
    
    def search_sync(self, query: str, limit: int = 30, category: str = "") -> list[SearchResult]:
        import re
        import requests
        
        results: list[SearchResult] = []
        arxiv_id_re = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")
        try:
            resp = requests.get(
                "https://api.openreview.net/notes/search",
                params={"term": query, "source": "forum", "limit": limit},
                timeout=30,
            )
            if resp.status_code != 200:
                return results
            data = resp.json()
        except Exception as e:
            logger.warning(f"  [openreview] 搜索失败: {e}")
            return results
        
        def safe_field(content: dict, key: str) -> str:
            val = content.get(key, "")
            if isinstance(val, dict):
                return str(val.get("value", val.get("content", "")))
            return str(val or "")
        
        for note in data.get("notes", []):
            content = note.get("content", {})
            title = safe_field(content, "title")
            abstract = safe_field(content, "abstract")
            forum_id = note.get("forum", "")
            
            arxiv_id = ""
            for key in ("arxiv_id", "paper_arxiv", "arXiv_id", "paper_id"):
                raw = content.get(key, "")
                if isinstance(raw, dict):
                    raw = raw.get("value", raw.get("content", ""))
                if raw:
                    m = arxiv_id_re.search(str(raw))
                    if m:
                        arxiv_id = m.group(1)
                        break
            
            if not arxiv_id:
                m = arxiv_id_re.search(str(content))
                if m:
                    arxiv_id = m.group(1)
            
            if not arxiv_id:
                continue
            
            results.append(SearchResult(
                arxiv_id=arxiv_id,
                title=title[:200],
                abstract=abstract[:500],
                source="openreview",
                source_url=f"https://openreview.net/forum?id={forum_id}",
                source_category=category,
                venue=note.get("invitation", "").replace(".*/.*", ""),
            ))
        
        return results


# ════════════════════════════════════════════
# 初始化注册
# ════════════════════════════════════════════

def init_registry():
    """初始化所有搜索器并注册"""
    register(HfCliSearcher())
    register(ArxivLocalSearcher())
    register(ArxivApiSearcher())
    register(OpenReviewSearcher())

    available = get_available()
    logger.info(f"搜索注册表就绪: {len(available)}/{len(_searchers)} 个可用")
    for s in available:
        logger.debug(f"  {s.name} (priority={s.priority})")
