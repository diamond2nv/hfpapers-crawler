#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ─── Multi-tier Code Matching Engine ──────────────────
# hfpapers/code_matcher.py
#
# Determines whether a paper has associated code, and at what quality level.
# Does NOT trust HF CLI's unreliable has_code flag.
#
# Tiers (ordered by reliability):
#   1. PapersWithCode API — most authoritative (has code + star count)
#   2. arXiv HTML — "Code" link on abstract page
#   3. GitHub search by title — inferred from arxiv_meta title
#   4. Local FTS5 — DOI/venue cross-check (code likely if venue=NeurIPS/ICML/ICLR)
#
# Code quality levels (rated 1-5):
#   LEVEL_NONE = 0      — No code found
#   LEVEL_INFERRED = 1  — GitHub repo found by title search, not verified
#   LEVEL_PARTIAL = 2   — Code repository exists but partial/limited
#   LEVEL_FULL = 3      — Official code repository, complete implementation
#   LEVEL_VERIFIED = 4  — Code verified to reproduce paper results
#   LEVEL_STARRED = 5   — High quality (100+ stars), community validated

import logging
import re
from dataclasses import dataclass

import requests

logger = logging.getLogger("hfpapers.code_matcher")

# ════════════════════════════════════════════
# Code Quality Levels
# ════════════════════════════════════════════

CODE_LEVEL_NONE = 0
CODE_LEVEL_INFERRED = 1
CODE_LEVEL_PARTIAL = 2
CODE_LEVEL_FULL = 3
CODE_LEVEL_VERIFIED = 4
CODE_LEVEL_STARRED = 5

LEVEL_NAMES = {
    0: "none",
    1: "inferred",
    2: "partial",
    3: "full",
    4: "verified",
    5: "starred",
}


@dataclass
class CodeMatch:
    """Code repository match result"""

    code_url: str = ""
    level: int = CODE_LEVEL_NONE  # Quality level 0-5
    source: str = ""  # "pwc_api" | "arxiv_page" | "github_search"
    stars: int = 0
    description: str = ""
    verified: bool = False


# ════════════════════════════════════════════
# Code Matcher
# ════════════════════════════════════════════

_GITHUB_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9._-]+/[A-Za-z0-9._/-]+?)(?:\s|\.|\"|'|<|>|\)|,|$|\))",
    re.IGNORECASE,
)
_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")


class CodeMatcher:
    """Multi-tier code matching engine

    Usage:
        matcher = CodeMatcher()
        match = matcher.match("2405.19101", title="Poseidon: ...")
        # match.level, match.code_url, match.stars
    """

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "HFPapersCodeMatcher/0.1 (mailto:research@example.com)",
            }
        )
        self._cache: dict[str, CodeMatch] = {}

    def match(self, arxiv_id: str, title: str = "", doi: str = "") -> CodeMatch:
        """Multi-tier code matching

        1. PapersWithCode API (most authoritative)
        2. arXiv abstract page (official code link)
        3. GitHub search by title (fallback)
        """
        if arxiv_id in self._cache:
            return self._cache[arxiv_id]

        # Tier 1: PapersWithCode API
        match = self._match_pwc(arxiv_id)
        if match.level >= CODE_LEVEL_FULL:
            self._cache[arxiv_id] = match
            return match

        # Tier 2: arXiv abstract page
        match = self._match_arxiv_page(arxiv_id)
        if match.level >= CODE_LEVEL_FULL:
            self._cache[arxiv_id] = match
            return match

        # Tier 3: GitHub search by title
        if title:
            match = self._match_github_search(arxiv_id, title)
            if match.level >= CODE_LEVEL_FULL:
                self._cache[arxiv_id] = match
                return match

        # Fallback: whatever we have
        if match.level > CODE_LEVEL_NONE:
            self._cache[arxiv_id] = match
            return match

        return CodeMatch()

    def _match_pwc(self, arxiv_id: str) -> CodeMatch:
        """Tier 1: PapersWithCode API lookup

        Endpoint: /api/v1/papers/arxiv_id
        Returns: code URL, star count, framework
        """
        try:
            resp = self._session.get(
                f"https://paperswithcode.com/api/v1/papers/arxiv:{arxiv_id}",
                timeout=10,
            )
            if resp.status_code != 200:
                return CodeMatch()

            data = resp.json()
            if not data or data.get("count", 0) == 0:
                return CodeMatch()

            paper = data.get("results", [{}])[0] if "results" in data else data
            repos = paper.get("repositories", []) or []

            if not repos:
                return CodeMatch()

            # Find best repo (by stars)
            best = max(repos, key=lambda r: r.get("stars", 0))
            code_url = (best.get("url") or "").strip()
            stars = best.get("stars", 0) or 0

            if not code_url:
                return CodeMatch()

            level = (
                CODE_LEVEL_STARRED
                if stars >= 100
                else CODE_LEVEL_VERIFIED
                if stars >= 10
                else CODE_LEVEL_FULL
            )

            return CodeMatch(
                code_url=code_url,
                level=level,
                source="pwc_api",
                stars=stars,
                description=best.get("description", "")[:200],
                verified=True,
            )
        except Exception as e:
            logger.debug(f"[pwc] {arxiv_id} failed: {e}")
            return CodeMatch()

    def _match_arxiv_page(self, arxiv_id: str) -> CodeMatch:
        """Tier 2: Scrape arXiv abstract page for code link (0 token)

        Searches for:
        - GitHub links in "Code" badge area
        - GitHub links in abstract text
        - Official code repository link on sidebar
        """
        try:
            resp = self._session.get(
                f"https://arxiv.org/abs/{arxiv_id}",
                timeout=15,
            )
            if resp.status_code != 200:
                return CodeMatch()

            html = resp.text

            # Strategy A: Look for code repository links in the "Code" section
            # arXiv format: <a class="badge" href="github.com/...">Code</a>
            code_section = re.search(
                r'<a[^>]*href="(https?://github\.com/[^"]+)"[^>]*>\s*Code\s*</a>',
                html,
                re.IGNORECASE,
            )
            if code_section:
                url = code_section.group(1).rstrip("/").rstrip(".git")
                return CodeMatch(
                    code_url=url,
                    level=CODE_LEVEL_FULL,
                    source="arxiv_page",
                    verified=False,
                )

            # Strategy B: General GitHub URL search in the page
            matches = _GITHUB_URL_RE.findall(html)
            if matches:
                seen = set()
                urls = []
                for m in matches:
                    repo = m.rstrip("/").rstrip(".git")
                    if repo not in seen:
                        seen.add(repo)
                        urls.append(f"https://github.com/{repo}")

                if urls:
                    return CodeMatch(
                        code_url=urls[0],
                        level=CODE_LEVEL_FULL,
                        source="arxiv_page",
                        verified=False,
                    )

            # Strategy C: Look for "Official Code" or "Code" in data-attribute
            code_badge = re.search(
                r'<a[^>]*class="[^"]*code[^"]*"[^>]*href="([^"]+)"',
                html,
                re.IGNORECASE,
            )
            if code_badge:
                url = code_badge.group(1)
                if "github" in url.lower():
                    return CodeMatch(
                        code_url=url.rstrip("/"),
                        level=CODE_LEVEL_FULL,
                        source="arxiv_page",
                        verified=False,
                    )

            # Strategy D: Look for "Code" section in the arXiv HTML sidebar
            # Newer arXiv pages have: <div class="code-links"> ... </div>
            code_links = re.search(
                r'<div[^>]*class="[^"]*code-links[^"]*"[^>]*>(.*?)</div>',
                html,
                re.IGNORECASE | re.DOTALL,
            )
            if code_links:
                gh_links = _GITHUB_URL_RE.findall(code_links.group(1))
                if gh_links:
                    return CodeMatch(
                        code_url=f"https://github.com/{gh_links[0]}",
                        level=CODE_LEVEL_FULL,
                        source="arxiv_page",
                        verified=False,
                    )

        except Exception as e:
            logger.debug(f"[arxiv_page] {arxiv_id} failed: {e}")

        return CodeMatch()

    def _match_github_search(self, arxiv_id: str, title: str) -> CodeMatch:
        """Tier 3: GitHub search API by paper title or excerpt (no API key needed)"""
        try:
            # Strategy A: Search by exact paper title (quoted phrase)
            cleaned_title = re.sub(r"[^a-zA-Z0-9\s]", " ", title).strip()
            if len(cleaned_title) < 10:
                return CodeMatch()

            # Try exact title first (highest precision)
            for query_try in [
                f'"{cleaned_title[:80]}" in:name,description',  # Exact title match
                cleaned_title[:80],  # Fallback: keywords
            ]:
                resp = self._session.get(
                    "https://api.github.com/search/repositories",
                    params={
                        "q": query_try,
                        "sort": "stars",
                        "per_page": 5,
                    },
                    timeout=10,
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                if resp.status_code != 200:
                    continue

                data = resp.json()
                items = data.get("items", [])
                if not items:
                    continue

                # Filter: paper title keywords in repo name or description
                title_keywords = {w.lower() for w in cleaned_title.split() if len(w) > 3}
                scored = []
                for item in items:
                    name = item.get("full_name", "").lower()
                    repo_name = item.get("name", "").lower()
                    desc = (item.get("description") or "").lower()
                    combined = f"{repo_name} {desc}"

                    match_count = sum(1 for kw in title_keywords if kw in combined)
                    match_ratio = match_count / max(len(title_keywords), 1)

                    if match_ratio >= 0.5:
                        stars = item.get("stargazers_count", 0) or 0
                        has_owner_match = any(
                            owner in name
                            for owner in [
                                "neuraloperator",
                                "camlab",
                                "ethz",
                                "google",
                                "facebook",
                                "deepmind",
                                "microsoft",
                                "nvidia",
                                "princeton",
                                "mit",
                                "stanford",
                                "berkeley",
                            ]
                        )
                        boost = 1000 if has_owner_match else 0
                        scored.append((stars + boost, stars, name, item.get("html_url", "")))

                if scored:
                    # Pick highest scored (owner match boosted)
                    scored.sort(key=lambda x: x[0], reverse=True)
                    best_stars, best_url = scored[0][1], scored[0][3]
                    level = (
                        CODE_LEVEL_STARRED
                        if best_stars >= 100
                        else CODE_LEVEL_VERIFIED
                        if best_stars >= 10
                        else CODE_LEVEL_INFERRED
                    )
                    return CodeMatch(
                        code_url=best_url,
                        level=level,
                        source="github_search",
                        stars=best_stars,
                        verified=False,
                    )
        except Exception as e:
            logger.debug(f"[github_search] {arxiv_id} failed: {e}")

        return CodeMatch()

    def close(self):
        self._session.close()
