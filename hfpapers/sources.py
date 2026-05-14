#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ─── Multi-source Crawl Engine ───────────────────
# hfpapers/sources.py
#
# Supported paper sources (prioritized):
#   hf_cli      — Hugging Face Papers CLI (primary, zero token)
#   openreview  — OpenReview reviews + papers
#   pwc_api     — PapersWithCode API (code+SOTA)
#   arxiv_api   — arXiv direct search (fallback, needs config)

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import requests

from hfpapers.config import get as cfg_get

logger = logging.getLogger("hfpapers.sources")

ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")

# ════════════════════════════════════════════
# Unified Paper Data Model
# ════════════════════════════════════════════


@dataclass
class SourcePaper:
    """Paper info extracted from any source"""

    arxiv_id: str = ""
    title: str = ""
    abstract: str = ""
    source: str = ""  # "hf_cli" | "openreview" | "pwc_api" | "arxiv_api"
    source_url: str = ""
    source_category: str = ""  # Search dimension label
    code_url: str = ""
    venue: str = ""  # Venue (e.g. "NeurIPS 2024")
    doi: str = ""  # DOI (official publication identifier)
    reviews: list[dict] = field(default_factory=list)  # OpenReview only: [(rating, comment)]


# ════════════════════════════════════════════
# Base Class
# ════════════════════════════════════════════


class PaperSource(ABC):
    """Abstract base class for paper sources"""

    @abstractmethod
    def search(self, query: str, category: str = "") -> list[SourcePaper]: ...

    @property
    @abstractmethod
    def name(self) -> str: ...


# ════════════════════════════════════════════
# 1. HF CLI — Primary source
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
                capture_output=True,
                text=True,
                timeout=60,
            )
            if output.returncode != 0:
                return results
            data = json.loads(output.stdout)
        except Exception as e:
            logger.debug(f"[hf_cli] {query} failed: {e}")
            return results

        for pd in data:
            aid = pd.get("id", "")
            if not aid or not ARXIV_ID_RE.match(aid):
                continue
            results.append(
                SourcePaper(
                    arxiv_id=aid,
                    title=pd.get("title", ""),
                    abstract=pd.get("summary", ""),
                    source="hf_cli",
                    source_url=f"https://huggingface.co/papers?q={query}",
                    source_category=category,
                )
            )
        logger.info(f"  [hf_cli] {query}: {len(results)} papers")
        return results


# ════════════════════════════════════════════
# 2. OpenReview — Reviews + Papers
# 2. OpenReview — Reviews + Papers
#
# API: POST https://api.openreview.net/notes/search
#   body: {"term": "neural operator", "content": "all", "limit": 50, "offset": 0}
#  Returns id (forum's forum), directly mappable to arXiv.
#  The OpenReview invitation field indicates the venue/workshop.
#
# Review data: each submission note's replies contain review notes,
#   with ratings (1-10) and reviewer_comment.


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
                logger.warning(f"  [openreview] API returned {resp.status_code}")
                return results
            data = resp.json()
        except Exception as e:
            logger.warning(f"  [openreview] search failed: {e}")
            return results

        notes = data.get("notes", [])
        for note in notes:
            content = note.get("content", {})
            # OpenReview content is nested dict: {"title": {"value": "..."}, "abstract": {"value": "..."}}
            title = _safe_field(content, "title")
            abstract = _safe_field(content, "abstract")
            forum_id = note.get("forum", "")

            # Extract arXiv ID
            arxiv_id = self._extract_arxiv(content)
            if not arxiv_id:
                # Search entire content JSON text
                arxiv_id = self._extract_arxiv_from_text(str(content))

            if not arxiv_id:
                continue

            # Extract review info
            reviews = self._fetch_reviews(forum_id) if forum_id else []

            # Extract venue
            venue = note.get("invitation", "").replace(".*/.*", "")

            results.append(
                SourcePaper(
                    arxiv_id=arxiv_id,
                    title=title[:200],
                    abstract=abstract[:500],
                    source="openreview",
                    source_url=f"https://openreview.net/forum?id={forum_id}",
                    source_category=category,
                    venue=venue,
                    reviews=reviews,
                )
            )

        logger.info(f"  [openreview] {query}: {len(results)} papers (with reviews)")
        return results

    def _extract_arxiv(self, content: dict) -> str:
        """Extract arXiv ID from OpenReview content dict"""
        for key in ("arxiv_id", "paper_arxiv", "arXiv_id", "paper_id"):
            raw = content.get(key, "")
            if isinstance(raw, dict):
                raw = raw.get("value", raw.get("content", ""))
            if not raw:
                # May be in html field
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
        """Fetch OpenReview review records"""
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
            logger.debug(f"  [openreview] failed to fetch reviews: {e}")
        return reviews


# ════════════════════════════════════════════
# 3. PapersWithCode — Code + SOTA Leaderboards
# ════════════════════════════════════════════
#
# API: GET https://paperswithcode.com/api/v1/papers/?q=<query>
#  Returns json: {count, next, previous, results: [
#   {id, title, arxiv_id, paper_pwc_url, paper_url, abstract, repositories, ...}  ]}
#  Each paper's repositories contain github_url, is_official etc.


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
                logger.warning(f"  [pwc] API returned {resp.status_code}")
                return results
            data = resp.json()
        except Exception as e:
            logger.warning(f"  [pwc] search failed: {e}")
            return results

        for paper in data.get("results", []):
            arxiv_id = paper.get("arxiv_id", "") or self._extract_arxiv_id(
                paper.get("paper_url", "")
            )
            if not arxiv_id or not ARXIV_ID_RE.match(arxiv_id):
                continue

            # Extract code repository
            code_url = ""
            repos = paper.get("repositories", [])
            for repo in repos:
                url = repo.get("github_url", "") or repo.get("url", "")
                if url and (repo.get("is_official") or not code_url):
                    code_url = url
                    if repo.get("is_official"):
                        break

            results.append(
                SourcePaper(
                    arxiv_id=arxiv_id,
                    title=paper.get("title", ""),
                    abstract=paper.get("abstract", ""),
                    source="pwc_api",
                    source_url=paper.get("paper_pwc_url", ""),
                    source_category=category,
                    code_url=code_url,
                )
            )

        logger.info(
            f"  [pwc] {query}: {len(results)} papers ({sum(1 for r in results if r.code_url)} with code)"
        )
        return results

    @staticmethod
    def _extract_arxiv_id(url: str) -> str:
        match = ARXIV_ID_RE.search(url)
        return match.group(1) if match else ""


# ════════════════════════════════════════════
# 4. arXiv API — Direct Search (Fallback)
# ════════════════════════════════════════════
#
# API: GET http://export.arxiv.org/api/query?search_query=...
#  Returns Atom XML


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
                # arXiv format: http://arxiv.org/abs/XXXX.YYYYYvN
                match = ARXIV_ID_RE.search(aid.text)
                if not match:
                    continue
                arxiv_id = match.group(1)
                title_tag = entry.find("title")
                abstract_tag = entry.find("summary")
                results.append(
                    SourcePaper(
                        arxiv_id=arxiv_id,
                        title=title_tag.text.strip()[:200] if title_tag else "",
                        abstract=abstract_tag.text.strip()[:500] if abstract_tag else "",
                        source="arxiv_api",
                        source_url=f"https://arxiv.org/abs/{arxiv_id}",
                        source_category=category,
                    )
                )
        except Exception as e:
            logger.warning(f"  [arxiv_api] search failed: {e}")
        logger.info(f"  [arxiv_api] {query}: {len(results)} papers")
        return results


# ════════════════════════════════════════════
# Multi-source Unified Dispatch
# ════════════════════════════════════════════


def get_enabled_sources() -> list[PaperSource]:
    """Return list of enabled sources based on config"""
    sources_map: dict[str, PaperSource] = {
        "hf_cli": HfCliSource(),
        "openreview": OpenReviewSource(),
        "pwc_api": PwcApiSource(),
        "arxiv_api": ArxivApiSource(),
    }
    enabled_names = cfg_get("sources.enabled", ["hf_cli"])
    return [sources_map[n] for n in enabled_names if n in sources_map]


def get_raw_searchers() -> list:
    """Get programmatic searchers (0 token), for large-scale batch search

    Returns:
        [(name, search_fn), ...]
        search_fn(query, limit, year_from) -> list[dict]

    Priority:
        1. arxiv_local — Local FTS5 index (millisecond)
        2. arxiv_api — arXiv HTTP API (fallback)
    """
    searchers = []

    # 1. Local FTS5 index (highest priority, 0 network requests)
    try:
        from hfpapers.arxiv_search import ArxivLocalSpider

        local = ArxivLocalSpider()
        # Check if there is data
        if local.engine.count() > 100:
            searchers.append(("arxiv_local", local.search))
            logger.info("[SOURCES] Local FTS5 index available")
    except Exception as e:
        logger.debug(f"[SOURCES] Local index unavailable: {e}")

    # 2. arXiv API (fallback)
    searchers.append(("arxiv_api", ArxivApiSource().search))

    return searchers


def deduplicate(papers: list[SourcePaper]) -> list[SourcePaper]:
    """Deduplicate by arxiv_id (keep first occurrence)"""
    seen: set[str] = set()
    result = []
    for p in papers:
        if p.arxiv_id and p.arxiv_id not in seen:
            seen.add(p.arxiv_id)
            result.append(p)
    return result


# ════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════


def _safe_field(content: dict, key: str) -> str:
    """Get value from OpenReview's nested content: {'key': {'value': '...'}}"""
    val = content.get(key, "")
    if isinstance(val, dict):
        return str(val.get("value", val.get("content", "")))
    return str(val or "")


def _safe_text(value) -> str:
    if isinstance(value, dict):
        return str(value.get("value", ""))
    return str(value or "")
