#!/usr/bin/env python3
"""
[LEGACY — deprecated, no longer used]
Multi-source spider — migrated to SearchDispatcher (hfpapers/searcher_registry.py + hfpapers/search_queue.py)

Retained for Scrapy middleware and item pipeline compatibility.
New development should use HFPapersCrawler (evolved.py) or SearchDispatcher directly.

Each Spider is responsible for crawling data from one source, outputting unified PaperItem.
Provides a resilient distributed crawling framework via Scrapy's concurrency, dedup, and middleware chain.
"""

import logging
import re
from typing import Optional
from urllib.parse import urlencode

import scrapy
from scrapy.http import Request, TextResponse

from hfpapers.config import get as cfg_get
from hfpapers.config import load_config
from hfpapers.items import PaperItem

logger = logging.getLogger(__name__)

ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")
# ─── Reusable Utility Functions ─────────────────────────


def _extract_arxiv_id(text: str) -> Optional[str]:
    m = ARXIV_ID_RE.search(text)
    return m.group(1) if m else None


def _safe_field(content: dict, key: str) -> str:
    val = content.get(key, "")
    if isinstance(val, dict):
        return str(val.get("value", val.get("content", "")))
    return str(val or "")


# ════════════════════════════════════════════
# 1. arXiv Search Spider — search arXiv API directly
# ════════════════════════════════════════════


class ArxivSearchSpider(scrapy.Spider):
    """arXiv API Search Spider

    Search parameters: search_query, start, max_results
    Returns Atom XML, each <entry> contains id/title/summary/authors/categories
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
            "CONCURRENT_REQUESTS": 2,  # arXiv is strict, keep concurrency low
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
        """Parse arXiv Atom XML feed"""
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

            # Extract categories
            cats = entry.find_all("category")
            paper["categories"] = [c.get("term", "") for c in cats if c.get("term")]

            yield paper


# ════════════════════════════════════════════
# 2. OpenReview Spider — search + reviews
# ════════════════════════════════════════════


class OpenReviewSpider(scrapy.Spider):
    """OpenReview Search Spider

    API: GET /notes/search?term=<query>&source=forum
    Returns JSON {notes: [{id, forum, content, invitation, ...}]}

    Content is nested: {"title": {"value": "..."}, "abstract": {"value": "..."}}
    arXiv ID may be in arxiv_id or html fields

    Additionally fetches:
      - venue = extracted from invitation (e.g. "NeurIPS 2024/Conference")
      - Reviews = GET /notes?forum=<forum_id> filtering notes where invitation contains "Review"
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
            "ROBOTSTXT_OBEY": False,  # API endpoint has no robots restriction
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

            # Extract arXiv ID
            arxiv_id = self._extract_arxiv(content)
            if not arxiv_id:
                continue

            # Extract venue
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

            # If forum_id exists, fetch reviews asynchronously
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
        """Search OpenReview content dict for arXiv ID (search all field values)

        Search order:
          1. Dedicated arxiv_id field
          2. _bibtex field (BibTeX format with eprint)
          3. pdf field (URL may contain arXiv ID)
          4. Full-text search across all fields
        """
        import json as _json
        import re as _re

        # 1. Priority fields
        for key in ("arxiv_id", "paper_arxiv", "arXiv_id", "paper_id"):
            raw = content.get(key, "")
            if isinstance(raw, dict):
                raw = raw.get("value", "")
            if raw:
                aid = _extract_arxiv_id(str(raw))
                if aid:
                    return aid

        # 2. BibTeX field
        bib = content.get("_bibtex", "")
        if isinstance(bib, dict):
            bib = bib.get("value", "")
        if bib:
            m = _re.search(r"eprint\s*=\s*[{](\d{4}\.\d{4,5})", str(bib))
            if m:
                return m.group(1)

        # 3. pdf field
        pdf = content.get("pdf", "")
        if isinstance(pdf, dict):
            pdf = pdf.get("value", "")
        if pdf:
            aid = _extract_arxiv_id(str(pdf))
            if aid:
                return aid

        # 4. Full-text global search
        all_text = _json.dumps(content)
        return _extract_arxiv_id(all_text)


# ════════════════════════════════════════════
# 3. HF Papers Spider — scrape HF Paper pages
# ════════════════════════════════════════════
# HF Papers pages are SSR, HTML can be parsed directly
# Each paper card contains: h3 title, arxiv ID, github link, upvote, trending
# Search: https://huggingface.co/papers?q=<query>&date=...
# Or hf CLI but Scrapy approach: scrape pages directly


class HfPapersSpider(scrapy.Spider):
    """HuggingFace Papers Search Spider

    Crawl HF Papers pages or Trending pages to extract paper metadata
    Supports pagination (?p=N)
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
        """Parse paper list page"""
        category = response.meta.get("category", "")
        page = response.meta.get("page", 1)

        # Each paper card
        for paper_card in response.css("article, div[class*='paper'], div[class*='card']"):
            title = paper_card.css("h3::text, h2::text, a[href*='/papers/']::text").get()
            if not title:
                continue

            # Find arXiv ID
            arxiv_id = ""
            for link in paper_card.css("a[href*='arxiv']::attr(href)").getall():
                aid = _extract_arxiv_id(link)
                if aid:
                    arxiv_id = aid
                    break
            if not arxiv_id:
                continue

            # Find GitHub code link
            code_url = ""
            for link in paper_card.css("a[href*='github.com']::attr(href)").getall():
                code_url = link
                break

            # Abstract
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

        # Pagination
        next_link = response.css("a:contains('Next'), a[rel='next']::attr(href), a.pagination__next::attr(href)").get()
        if next_link and page < self.max_pages:
            yield Request(
                url=response.urljoin(next_link),
                callback=self.parse_list,
                meta={"category": category, "page": page + 1},
            )


# ════════════════════════════════════════════
# 4. Multi-source Generic Spider — reads sources from config
# ════════════════════════════════════════════


class MultiSourceSpider(scrapy.Spider):
    """Multi-source unified spider — reads all queries + sources from config.yaml

    Config-driven generic Spider, suitable for multi-machine deployment.
    Each machine can be configured with different sources/queries for distributed workload.

    Usage:
      scrapy crawl multi_source -a source=hf_papers   # Crawl HF only
      scrapy crawl multi_source                       # Crawl all enabled sources
    """
    name = "multi_source"

    def __init__(self, source: str = "", *args, **kwargs):
        super().__init__(*args, **kwargs)
        cfg = load_config()
        self.queries = cfg.get("search", {}).get("queries", [])
        self.enabled_sources = cfg.get("sources", {}).get("enabled", ["hf_papers"])
        self.source_filter = source  # If source arg specified, only crawl this source

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

                # Delegate request generation to sub-spider
                sub = spider_cls(query=query, category=category)
                for req in sub.start_requests():
                    yield req
