#!/usr/bin/env python3
"""
[LEGACY — 废弃，不再使用]
多源爬虫 Spider — 已迁移到 SearchDispatcher (hfpapers/searcher_registry.py + hfpapers/search_queue.py)

遗留原因: 保留给 Scrapy 中间件和 item pipeline 兼容。
新开发请使用 HFPapersCrawler (evolved.py) 或 SearchDispatcher 直接搜索。

每个 Spider 负责一种来源的数据爬取，输出统一的 PaperItem。
通过 Scrapy 的并发、去重、中间件链提供弹性分布式爬虫框架。
"""

import json
import logging
import re
from urllib.parse import urlencode
from typing import Optional

import scrapy
from scrapy.http import Request, TextResponse

from hfpapers.items import PaperItem
from hfpapers.config import get as cfg_get, load_config

logger = logging.getLogger(__name__)

ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")
# ─── 可复用工具函数 ─────────────────────────


def _extract_arxiv_id(text: str) -> Optional[str]:
    m = ARXIV_ID_RE.search(text)
    return m.group(1) if m else None


def _safe_field(content: dict, key: str) -> str:
    val = content.get(key, "")
    if isinstance(val, dict):
        return str(val.get("value", val.get("content", "")))
    return str(val or "")


# ════════════════════════════════════════════
# 1. arXiv Search Spider — 直接搜索 arXiv API
# ════════════════════════════════════════════


class ArxivSearchSpider(scrapy.Spider):
    """arXiv API 搜索蜘蛛
    
    搜索条件: search_query, start, max_results
    返回 Atom XML, 每个 <entry> 含 id/title/summary/authors/categories
    """
    name = "arxiv_search"
    allowed_domains = ["export.arxiv.org"]
    base_url = "http://export.arxiv.org/api/query"

    def __init__(self, query: str = "", category: str = "", max_results: int = 50, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.search_query = query or cfg_get("search.queries", [{}])[0].get("query", "neural operator")
        self.search_category = category or "arxiv-default"
        self.max_results = max_results
        self.custom_settings = {
            "DOWNLOAD_DELAY": cfg_get("search.sources.arxiv.delay_sec", 3.0),
            "CONCURRENT_REQUESTS": 2,  # arXiv 限制严，并发不要高
            "ROBOTSTXT_OBEY": True,
        }

    def start_requests(self):
        params = urlencode({
            "search_query": f"all:{self.search_query}",
            "max_results": self.max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        })
        yield Request(
            url=f"{self.base_url}?{params}",
            callback=self.parse_feed,
            meta={"category": self.search_category},
        )

    def parse_feed(self, response: TextResponse):
        """解析 arXiv Atom XML feed"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, "lxml")
        category = response.meta.get("category", "")

        for entry in soup.find_all("entry"):
            arxiv_id = _extract_arxiv_id(entry.find("id").text.strip() if entry.find("id") else "")
            if not arxiv_id:
                continue

            title = entry.find("title")
            abstract = entry.find("summary")

            paper = PaperItem(
                arxiv_id=arxiv_id,
                title=title.text.strip()[:200] if title else "",
                abstract=abstract.text.strip()[:500] if abstract else "",
                source="arxiv_api",
                source_url=f"https://arxiv.org/abs/{arxiv_id}",
                search_category=category,
            )

            # 提取 categories
            cats = entry.find_all("category")
            paper["categories"] = [c.get("term", "") for c in cats if c.get("term")]

            yield paper


# ════════════════════════════════════════════
# 2. OpenReview Spider — 搜索 + 审稿
# ════════════════════════════════════════════


class OpenReviewSpider(scrapy.Spider):
    """OpenReview 搜索蜘蛛
    
    API: GET /notes/search?term=<query>&source=forum
    返回 JSON {notes: [{id, forum, content, invitation, ...}]}
    
    content 嵌套: {"title": {"value": "..."}, "abstract": {"value": "..."}}
    arXiv ID 可能在 arxiv_id 或 html 字段中
    
    额外获取:
      - venue = invitation 中提取（如 "NeurIPS 2024/Conference"）
      - 审稿 = GET /notes?forum=<forum_id> 过滤 invitation 含 "Review" 的 notes
    """
    name = "openreview"
    allowed_domains = ["api.openreview.net"]
    base_url = "https://api.openreview.net"

    def __init__(self, query: str = "", category: str = "", max_results: int = 50, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.search_query = query or cfg_get("search.queries", [{}])[0].get("query", "neural operator")
        self.search_category = category or "openreview-default"
        self.max_results = max_results
        self.custom_settings = {
            "DOWNLOAD_DELAY": 1.0,
            "CONCURRENT_REQUESTS": 3,
            "ROBOTSTXT_OBEY": False,  # API 端没有 robots 限制
        }

    def start_requests(self):
        params = urlencode({"term": self.search_query, "source": "forum", "limit": self.max_results})
        yield Request(
            url=f"{self.base_url}/notes/search?{params}",
            callback=self.parse_search,
            meta={"category": self.search_category},
        )

    def parse_search(self, response: TextResponse):
        data = response.json()
        notes = data.get("notes", [])
        category = response.meta.get("category", "")

        for note in notes:
            content = note.get("content", {})
            title = _safe_field(content, "title")
            abstract = _safe_field(content, "abstract")
            forum_id = note.get("forum", "")

            # 提取 arXiv ID
            arxiv_id = self._extract_arxiv(content)
            if not arxiv_id:
                continue

            # 提取 venue
            invitation = note.get("invitation", "")
            venue = invitation.split("/")[0] if "/" in invitation else invitation

            paper = PaperItem(
                arxiv_id=arxiv_id,
                title=title[:200],
                abstract=abstract[:500],
                source="openreview",
                source_url=f"https://openreview.net/forum?id={forum_id}",
                search_category=category,
                venue=venue,
                openreview_forum=forum_id,
            )

            # 如果有 forum_id，异步获取审稿
            if forum_id:
                yield Request(
                    url=f"{self.base_url}/notes?{urlencode({'forum': forum_id, 'limit': 100})}",
                    callback=self.parse_reviews,
                    meta={"paper": paper},
                )
            else:
                yield paper

    def parse_reviews(self, response: TextResponse):
        paper = response.meta.get("paper", {})
        data = response.json()
        reviews = []
        for note in data.get("notes", []):
            inv = note.get("invitation", "")
            if "Review" not in inv and "Official_Review" not in inv:
                continue
            content = note.get("content", {})
            rating = _safe_field(content, "rating") or _safe_field(content, "recommendation")
            comment = _safe_field(content, "review") or _safe_field(content, "reviewer_comment")
            reviews.append({"rating": rating, "comment": comment[:300]})

        paper = PaperItem(**paper) if isinstance(paper, dict) else paper
        if reviews:
            paper["reviews"] = reviews
        yield paper

    @staticmethod
    def _extract_arxiv(content: dict) -> Optional[str]:
        """从 OpenReview 的 content 字典搜索 arXiv ID（搜所有字段的值）

        搜索顺序:
          1. 专门的 arxiv_id 字段
          2. _bibtex 字段（BibTeX 格式含 eprint）
          3. pdf 字段（URL 中可能含 arXiv ID）
          4. 全字段文本搜索
        """
        import re as _re
        import json as _json

        # 1. 优先字段
        for key in ("arxiv_id", "paper_arxiv", "arXiv_id", "paper_id"):
            raw = content.get(key, "")
            if isinstance(raw, dict):
                raw = raw.get("value", "")
            if raw:
                aid = _extract_arxiv_id(str(raw))
                if aid:
                    return aid

        # 2. BibTeX 字段
        bib = content.get("_bibtex", "")
        if isinstance(bib, dict):
            bib = bib.get("value", "")
        if bib:
            m = _re.search(r"eprint\s*=\s*[{](\d{4}\.\d{4,5})", str(bib))
            if m:
                return m.group(1)

        # 3. pdf 字段
        pdf = content.get("pdf", "")
        if isinstance(pdf, dict):
            pdf = pdf.get("value", "")
        if pdf:
            aid = _extract_arxiv_id(str(pdf))
            if aid:
                return aid

        # 4. 全局文本搜索
        all_text = _json.dumps(content)
        return _extract_arxiv_id(all_text)


# ════════════════════════════════════════════
# 3. HF Papers Spider — 抓取 HF Paper 页面
# ════════════════════════════════════════════
# HF Papers 页面是 SSR 的，可以直接解析 HTML
# 每个 paper card 含: h3 标题, arxiv ID, github 链接, upvote, trending
# 搜索: https://huggingface.co/papers?q=<query>&date=...
# 或 hf CLI 但 Scrapy 方式：直接爬页面


class HfPapersSpider(scrapy.Spider):
    """HuggingFace Papers 搜索蜘蛛
    
    爬取 HF Papers 页面或 Trending 页面，提取论文元数据
    支持分页（?p=N 翻页）
    """
    name = "hf_papers"
    allowed_domains = ["huggingface.co"]
    base_url = "https://huggingface.co/papers"

    def __init__(self, query: str = "", category: str = "", max_pages: int = 3, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.search_query = query or ""
        self.search_category = category or "hf-papers"
        self.max_pages = max_pages
        self.custom_settings = {
            "DOWNLOAD_DELAY": cfg_get("search.sources.huggingface.delay_sec", 1.0),
            "CONCURRENT_REQUESTS": 3,
            "ROBOTSTXT_OBEY": True,
        }

    def start_requests(self):
        url = self.base_url
        if self.search_query:
            url += f"?q={self.search_query}"
        yield Request(
            url=url,
            callback=self.parse_list,
            meta={"category": self.search_category, "page": 1},
        )

    def parse_list(self, response: TextResponse):
        """解析论文列表页"""
        category = response.meta.get("category", "")
        page = response.meta.get("page", 1)

        # 每个 paper 卡片
        for paper_card in response.css("article, div[class*='paper'], div[class*='card']"):
            title = paper_card.css("h3::text, h2::text, a[href*='/papers/']::text").get()
            if not title:
                continue

            # 查找 arxiv ID
            arxiv_id = ""
            for link in paper_card.css("a[href*='arxiv']::attr(href)").getall():
                aid = _extract_arxiv_id(link)
                if aid:
                    arxiv_id = aid
                    break
            if not arxiv_id:
                continue

            # 查找 GitHub 代码链接
            code_url = ""
            for link in paper_card.css("a[href*='github.com']::attr(href)").getall():
                code_url = link
                break

            # 摘要
            abstract = paper_card.css("p::text, div[class*='abstract']::text").get()
            abstract = abstract.strip()[:500] if abstract else ""

            paper = PaperItem(
                arxiv_id=arxiv_id,
                title=title.strip()[:200],
                abstract=abstract,
                source="hf_papers",
                source_url=f"https://arxiv.org/abs/{arxiv_id}",
                search_category=category,
                code_url=code_url,
            )
            yield paper

        # 翻页
        next_link = response.css("a:contains('Next'), a[rel='next']::attr(href), a.pagination__next::attr(href)").get()
        if next_link and page < self.max_pages:
            yield Request(
                url=response.urljoin(next_link),
                callback=self.parse_list,
                meta={"category": category, "page": page + 1},
            )


# ════════════════════════════════════════════
# 4. 多站通用爬虫 — 从配置文件读取 sources
# ════════════════════════════════════════════


class MultiSourceSpider(scrapy.Spider):
    """多源统一爬虫 — 从 config.yaml 读取全部 queries + sources
    
    配置驱动的通用 Spider，适合部署到多台机器。
    每台机器可以配不同的 sources / queries 实现分布式分工。
    
    用法:
      scrapy crawl multi_source -a source=hf_papers   # 只爬 HF
      scrapy crawl multi_source                       # 爬全部启用的源
    """
    name = "multi_source"

    def __init__(self, source: str = "", *args, **kwargs):
        super().__init__(*args, **kwargs)
        cfg = load_config()
        self.queries = cfg.get("search", {}).get("queries", [])
        self.enabled_sources = cfg.get("sources", {}).get("enabled", ["hf_papers"])
        self.source_filter = source  # 如果指定了 source 参数，只爬这个源

    def start_requests(self):
        spider_cls_map = {
            "arxiv": ArxivSearchSpider,
            "openreview": OpenReviewSpider,
            "hf_papers": HfPapersSpider,
        }

        for q in self.queries:
            query = q.get("query", "")
            category = q.get("category", "default")

            for src_name in self.enabled_sources:
                if self.source_filter and src_name != self.source_filter:
                    continue

                spider_cls = spider_cls_map.get(src_name)
                if not spider_cls:
                    self.logger.warning(f"Unknown source: {src_name}")
                    continue

                # 委托子 spider 生成请求
                sub = spider_cls(query=query, category=category)
                for req in sub.start_requests():
                    yield req
