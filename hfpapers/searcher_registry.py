#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ─── Unified Search Registry ──────────────────────────
# hfpapers/searcher_registry.py
# All Searchers register here — supports both sync and async invocation

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("hfpapers.searcher_registry")

# ════════════════════════════════════════════
# Search Adapter Interface
# ════════════════════════════════════════════


@dataclass
class SearchResult:
    """Unified search result"""
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
    """Base searcher — must implement search_sync, search_async optional"""

    name: str = ""

    @abstractmethod
    def search_sync(self, query: str, limit: int = 30, category: str = "") -> list[SearchResult]:
        """Sync search (must implement)"""
        ...

    async def search_async(self, query: str, limit: int = 30, category: str = "") -> list[SearchResult]:
        """Async search (default: runs sync version in thread pool)"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.search_sync, query, limit, category,
        )

    @property
    def priority(self) -> int:
        """Search priority (lower = higher), default 100"""
        return 100

    def is_available(self) -> bool:
        """Whether available (checks API key / local data)"""
        return True


# ════════════════════════════════════════════
# Registry
# ════════════════════════════════════════════

_searchers: dict[str, BaseSearcher] = {}


def register(searcher: BaseSearcher):
    """Register a searcher"""
    if not searcher.name:
        raise ValueError("Searcher must have a name")
    _searchers[searcher.name] = searcher
    logger.debug(f"Register searcher: {searcher.name}")


def get(name: str) -> Optional[BaseSearcher]:
    return _searchers.get(name)


def get_all() -> dict[str, BaseSearcher]:
    return dict(_searchers)


def get_available() -> list[BaseSearcher]:
    """Return all available searchers (sorted by priority)"""
    available = [s for s in _searchers.values() if s.is_available()]
    available.sort(key=lambda s: s.priority)
    return available


def get_names() -> list[str]:
    return list(_searchers.keys())


# ════════════════════════════════════════════
# Adapt legacy searches to registry
# ════════════════════════════════════════════


class HfCliSearcher(BaseSearcher):
    name = "hf_cli"

    def search_sync(self, query: str, limit: int = 30, category: str = "") -> list[SearchResult]:
        import json
        import re
        import subprocess

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
            logger.debug(f"[hf_cli] {query} failed: {e}")
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
        logger.info(f"  [hf_cli] {query}: {len(results)} papers")
        return results


class ArxivLocalSearcher(BaseSearcher):
    name = "arxiv_local"

    @property
    def priority(self) -> int:
        return 1  # Highest priority (zero network overhead, millisecond latency)

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
        import warnings

        import requests
        from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
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
            logger.warning(f"  [arxiv_api] search failed: {e}")
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
            logger.warning(f"  [openreview] search failed: {e}")
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
# Registration Initialization
# ════════════════════════════════════════════

def init_registry():
    """Initialize and register all searchers"""
    register(HfCliSearcher())
    register(ArxivLocalSearcher())
    register(ArxivApiSearcher())
    register(OpenReviewSearcher())

    available = get_available()
    logger.info(f"Search registry ready: {len(available)}/{len(_searchers)} available")
    for s in available:
        logger.debug(f"  {s.name} (priority={s.priority})")
