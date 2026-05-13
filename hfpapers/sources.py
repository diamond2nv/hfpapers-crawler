# ─── 多源爬取引擎 ──────────────────────────
# hfpapers/sources.py
#
# 支持的论文来源（按优先级排列）:
#   hf_cli      — Hugging Face Papers CLI (主源，零 token)
#   openreview  — OpenReview 的审稿记录 + 论文
#   pwc_api     — PapersWithCode API (代码+SOTA)
#   arxiv_api   — arXiv 直接搜索 (备选，需要配置)

import json
import logging
import re
import time
import requests
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from hfpapers.config import get as cfg_get

logger = logging.getLogger("hfpapers.sources")

ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")

# ════════════════════════════════════════════
# 统一论文数据模型
# ════════════════════════════════════════════


@dataclass
class SourcePaper:
    """从任意来源提取的论文信息"""
    arxiv_id: str = ""
    title: str = ""
    abstract: str = ""
    source: str = ""               # "hf_cli" | "openreview" | "pwc_api" | "arxiv_api"
    source_url: str = ""
    source_category: str = ""      # 搜索维度标签
    code_url: str = ""
    venue: str = ""                # 会议/期刊 (如 "NeurIPS 2024")
    doi: str = ""                  # DOI (正式发表标识)
    reviews: list[dict] = field(default_factory=list)  # OpenReview 专属：[(分数, 意见)]


# ════════════════════════════════════════════
# 基类
# ════════════════════════════════════════════


class PaperSource(ABC):
    """论文来源的抽象基类"""

    @abstractmethod
    def search(self, query: str, category: str = "") -> list[SourcePaper]:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...


# ════════════════════════════════════════════
# 1. HF CLI — 主源
# ════════════════════════════════════════════


class HfCliSource(PaperSource):
    name = "hf_cli"

    def search(self, query: str, category: str = "") -> list[SourcePaper]:
        import subprocess
        results: list[SourcePaper] = []
        limit = cfg_get("search.max_per_dim", 30)
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

        for pd in data:
            aid = pd.get("id", "")
            if not aid or not ARXIV_ID_RE.match(aid):
                continue
            results.append(SourcePaper(
                arxiv_id=aid,
                title=pd.get("title", ""),
                abstract=pd.get("summary", ""),
                source="hf_cli",
                source_url=f"https://huggingface.co/papers?q={query}",
                source_category=category,
            ))
        logger.info(f"  [hf_cli] {query}: {len(results)} 篇")
        return results


# ════════════════════════════════════════════
# 2. OpenReview — 审稿记录 + 论文
# ════════════════════════════════════════════
#
# API: POST https://api.openreview.net/notes/search
#   body: {"term": "neural operator", "content": "all", "limit": 50, "offset": 0}
#  返回含 id  (forum 的 forum)，可直接对应 arXiv。
#  另外 OpenReview 的 invitation 字段表示所属会议/工作坊。
#
# 审稿数据：每个 submission note 的 replies 含 review notes，
#   其中有 ratings (1-10) 和 reviewer_comment。


class OpenReviewSource(PaperSource):
    name = "openreview"
    BASE = "https://api.openreview.net"

    def search(self, query: str, category: str = "") -> list[SourcePaper]:
        results: list[SourcePaper] = []
        limit = cfg_get("sources.openreview.max_results", 30)

        try:
            resp = requests.get(
                f"{self.BASE}/notes/search",
                params={"term": query, "source": "forum", "limit": limit},
                timeout=30,
            )
            if resp.status_code != 200:
                logger.warning(f"  [openreview] API 返回 {resp.status_code}")
                return results
            data = resp.json()
        except Exception as e:
            logger.warning(f"  [openreview] 搜索失败: {e}")
            return results

        notes = data.get("notes", [])
        for note in notes:
            content = note.get("content", {})
            # OpenReview 的 content 是嵌套 dict: {"title": {"value": "..."}, "abstract": {"value": "..."}}
            title = _safe_field(content, "title")
            abstract = _safe_field(content, "abstract")
            forum_id = note.get("forum", "")

            # 提取 arXiv ID
            arxiv_id = self._extract_arxiv(content)
            if not arxiv_id:
                # 搜索整个 content JSON 文本
                arxiv_id = self._extract_arxiv_from_text(str(content))

            if not arxiv_id:
                continue

            # 提取审稿信息
            reviews = self._fetch_reviews(forum_id) if forum_id else []

            # 提取 venue
            venue = note.get("invitation", "").replace(".*/.*", "")

            results.append(SourcePaper(
                arxiv_id=arxiv_id,
                title=title[:200],
                abstract=abstract[:500],
                source="openreview",
                source_url=f"https://openreview.net/forum?id={forum_id}",
                source_category=category,
                venue=venue,
                reviews=reviews,
            ))

        logger.info(f"  [openreview] {query}: {len(results)} 篇 (含审稿)")
        return results

    def _extract_arxiv(self, content: dict) -> str:
        """从 OpenReview 的 content 字典提取 arXiv ID"""
        for key in ("arxiv_id", "paper_arxiv", "arXiv_id", "paper_id"):
            raw = content.get(key, "")
            if isinstance(raw, dict):
                raw = raw.get("value", raw.get("content", ""))
            if not raw:
                # 可能在 html 字段里
                html_val = content.get("html", "")
                if isinstance(html_val, dict):
                    html_val = html_val.get("value", "")
                raw = html_val
            if raw:
                match = ARXIV_ID_RE.search(str(raw))
                if match:
                    return match.group(1)
        return ""

    def _extract_arxiv_from_text(self, text: str) -> str:
        match = ARXIV_ID_RE.search(text)
        return match.group(1) if match else ""

    def _fetch_reviews(self, forum_id: str) -> list[dict]:
        """获取 OpenReview 审稿记录"""
        reviews = []
        try:
            resp = requests.get(
                f"{self.BASE}/notes",
                params={"forum": forum_id, "limit": 100},
                timeout=15,
            )
            if resp.status_code != 200:
                return reviews
            data = resp.json()
            for note in data.get("notes", []):
                inv = note.get("invitation", "")
                if "Review" not in inv and "Official_Review" not in inv:
                    continue
                content = note.get("content", {})
                rating = _safe_field(content, "rating") or _safe_field(content, "recommendation")
                comment = _safe_field(content, "review") or _safe_field(content, "reviewer_comment")
                reviews.append({"rating": rating, "comment": comment[:300]})
        except Exception as e:
            logger.debug(f"  [openreview] 审稿获取失败: {e}")
        return reviews


# ════════════════════════════════════════════
# 3. PapersWithCode — 代码 + SOTA 排行榜
# ════════════════════════════════════════════
#
# API: GET https://paperswithcode.com/api/v1/papers/?q=<query>
#  返回 json: {count, next, previous, results: [
#   {id, title, arxiv_id, paper_pwc_url, paper_url, abstract, repositories, ...}  ]}
#  每个 paper 的 repositories 含 github_url, is_official 等


class PwcApiSource(PaperSource):
    name = "pwc_api"
    BASE = "https://paperswithcode.com/api/v1"

    def search(self, query: str, category: str = "") -> list[SourcePaper]:
        results: list[SourcePaper] = []
        limit = cfg_get("sources.pwc.max_results", 30)

        try:
            resp = requests.get(
                f"{self.BASE}/papers/",
                params={"q": query, "items_per_page": limit},
                timeout=30,
            )
            if resp.status_code != 200:
                logger.warning(f"  [pwc] API 返回 {resp.status_code}")
                return results
            data = resp.json()
        except Exception as e:
            logger.warning(f"  [pwc] 搜索失败: {e}")
            return results

        for paper in data.get("results", []):
            arxiv_id = paper.get("arxiv_id", "") or self._extract_arxiv_id(
                paper.get("paper_url", "")
            )
            if not arxiv_id or not ARXIV_ID_RE.match(arxiv_id):
                continue

            # 提取代码仓库
            code_url = ""
            repos = paper.get("repositories", [])
            for repo in repos:
                url = repo.get("github_url", "") or repo.get("url", "")
                if url and (repo.get("is_official") or not code_url):
                    code_url = url
                    if repo.get("is_official"):
                        break

            results.append(SourcePaper(
                arxiv_id=arxiv_id,
                title=paper.get("title", ""),
                abstract=paper.get("abstract", ""),
                source="pwc_api",
                source_url=paper.get("paper_pwc_url", ""),
                source_category=category,
                code_url=code_url,
            ))

        logger.info(f"  [pwc] {query}: {len(results)} 篇 (含 {sum(1 for r in results if r.code_url)} 个代码)")
        return results

    @staticmethod
    def _extract_arxiv_id(url: str) -> str:
        match = ARXIV_ID_RE.search(url)
        return match.group(1) if match else ""


# ════════════════════════════════════════════
# 4. arXiv API — 直接搜索（备选）
# ════════════════════════════════════════════
#
# API: GET http://export.arxiv.org/api/query?search_query=...
#  返回 Atom XML


class ArxivApiSource(PaperSource):
    name = "arxiv_api"
    BASE = "http://export.arxiv.org/api/query"

    def search(self, query: str, category: str = "") -> list[SourcePaper]:
        results: list[SourcePaper] = []
        max_results = cfg_get("sources.arxiv.max_results", 30)
        try:
            from bs4 import BeautifulSoup
            resp = requests.get(
                self.BASE,
                params={
                    "search_query": f"all:{query}",
                    "max_results": max_results,
                    "sortBy": "relevance",
                    "sortOrder": "descending",
                },
                timeout=30,
            )
            if resp.status_code != 200:
                return results
            soup = BeautifulSoup(resp.text, "lxml")
            for entry in soup.find_all("entry"):
                aid = entry.find("id")
                if not aid:
                    continue
                # arXiv 格式: http://arxiv.org/abs/XXXX.YYYYYvN
                match = ARXIV_ID_RE.search(aid.text)
                if not match:
                    continue
                arxiv_id = match.group(1)
                title_tag = entry.find("title")
                abstract_tag = entry.find("summary")
                results.append(SourcePaper(
                    arxiv_id=arxiv_id,
                    title=title_tag.text.strip()[:200] if title_tag else "",
                    abstract=abstract_tag.text.strip()[:500] if abstract_tag else "",
                    source="arxiv_api",
                    source_url=f"https://arxiv.org/abs/{arxiv_id}",
                    source_category=category,
                ))
        except Exception as e:
            logger.warning(f"  [arxiv_api] 搜索失败: {e}")
        logger.info(f"  [arxiv_api] {query}: {len(results)} 篇")
        return results


# ════════════════════════════════════════════
# 多源统一调度
# ════════════════════════════════════════════


def get_enabled_sources() -> list[PaperSource]:
    """根据配置返回启用的来源列表"""
    sources_map: dict[str, PaperSource] = {
        "hf_cli": HfCliSource(),
        "openreview": OpenReviewSource(),
        "pwc_api": PwcApiSource(),
        "arxiv_api": ArxivApiSource(),
    }
    enabled_names = cfg_get("sources.enabled", ["hf_cli"])
    return [sources_map[n] for n in enabled_names if n in sources_map]


def get_raw_searchers() -> list:
    """获取纯程序化搜索器（0 token），用于大规模批量搜索

    返回:
        [(name, search_fn), ...]
        search_fn(query, limit, year_from) -> list[dict]

    优先级:
        1. arxiv_local — 本地 FTS5 索引（毫秒级）
        2. arxiv_api — arXiv HTTP API（备选）
    """
    searchers = []

    # 1. 本地 FTS5 索引（最高优先级，0 网络请求）
    try:
        from hfpapers.arxiv_search import ArxivLocalSearch, ArxivLocalSpider
        local = ArxivLocalSpider()
        # 检查是否有数据
        if local.engine.count() > 100:
            searchers.append(("arxiv_local", local.search))
            logger.info("[SOURCES] 本地 FTS5 索引可用")
    except Exception as e:
        logger.debug(f"[SOURCES] 本地索引不可用: {e}")

    # 2. arXiv API（备选）
    searchers.append(("arxiv_api", ArxivApiSource().search))

    return searchers


def deduplicate(papers: list[SourcePaper]) -> list[SourcePaper]:
    """按 arxiv_id 去重（保留第一个出现的）"""
    seen: set[str] = set()
    result = []
    for p in papers:
        if p.arxiv_id and p.arxiv_id not in seen:
            seen.add(p.arxiv_id)
            result.append(p)
    return result


# ════════════════════════════════════════════
# 辅助
# ════════════════════════════════════════════


def _safe_field(content: dict, key: str) -> str:
    """从 OpenReview 的嵌套 content 中取值: {'key': {'value': '...'}}"""
    val = content.get(key, "")
    if isinstance(val, dict):
        return str(val.get("value", val.get("content", "")))
    return str(val or "")


def _safe_text(value) -> str:
    if isinstance(value, dict):
        return str(value.get("value", ""))
    return str(value or "")
