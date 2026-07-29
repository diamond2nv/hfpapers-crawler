#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
github_ingest.py — GitHub/DeepWiki repository ingestion adapter

Two modes:
  1. URL mode: ``hfpclawer source ingest github https://github.com/org/repo``
     → fetch README + repo metadata + optional DeepWiki summary → SourceDocument
  2. Local mode: ``hfpclawer source ingest github --dir ~/projects/repo``
     → scan local README + detect structure → SourceDocument

Output is a ``SourceDocument`` compatible with ``paper_store.ensure_paper()``,
stored with source="gh_ingest" for differentiation from arXiv papers.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from hfpapers.source_adapters import BaseSource, SourceDocument

logger = logging.getLogger("hfpapers.source_adapters.github")

# ── Constants ────────────────────────────────────────
GITHUB_API = "https://api.github.com"
RAW_CONTENT = "https://raw.githubusercontent.com"
DEEPWIKI_API = "https://deepwiki.ai/api/repo"

# ── GitHub URL patterns ──────────────────────────────
GH_RE_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([^/]+)/([^/\s?#]+)"
)
GH_RAW_PATTERN = re.compile(
    r"https?://raw\.githubusercontent\.com/([^/]+)/([^/\s?#]+)"
)
GH_SSH_PATTERN = re.compile(
    r"git@github\.com:([^/]+)/([^/\s.]+)"
)


def parse_github_url(url: str) -> tuple[str, str] | None:
    """Extract (owner, repo) from GitHub URL"""
    m = GH_RE_PATTERN.search(url)
    if m:
        return m.group(1), m.group(2).rstrip(".git")
    m = GH_RAW_PATTERN.search(url)
    if m:
        return m.group(1), m.group(2)
    m = GH_SSH_PATTERN.search(url)
    if m:
        return m.group(1), m.group(2).rstrip(".git")
    return None


def _github_api_request(url: str, headers: Optional[dict] = None) -> dict | None:
    """Make GET request to GitHub API with rate-limit handling"""
    if headers is None:
        headers = {"User-Agent": "hfpclawer/0.14.0", "Accept": "application/vnd.github.v3+json"}
    else:
        headers.setdefault("User-Agent", "hfpclawer/0.14.0")
        headers.setdefault("Accept", "application/vnd.github.v3+json")

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            logger.warning("GitHub API 403 (rate limit?) — trying raw fallback")
        elif e.code == 404:
            logger.info("GitHub API 404 — repo not found or private")
        else:
            logger.warning(f"GitHub API HTTP {e.code}: {e.reason[:80]}")
        return None
    except Exception as e:
        logger.warning(f"GitHub API error: {e}")
        return None


def _fetch_raw(url: str) -> str | None:
    """Fetch raw content (README, etc.) — fallback when API fails"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hfpclawer/0.14.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


class GitHubSource(BaseSource):
    """GitHub/DeepWiki repository ingestion adapter"""

    name = "gh_ingest"

    def search(self, query: str, limit: int = 10) -> list[SourceDocument]:
        """Search GitHub by keyword — uses GitHub repo search API"""
        url = f"{GITHUB_API}/search/repositories?q={urllib.parse.quote(query)}&per_page={limit}&sort=stars"
        # Note: uses raw query string → GitHub search
        data = _github_api_request(url)
        if not data or "items" not in data:
            return []

        results = []
        for item in data["items"][:limit]:
            doc = self._repo_item_to_doc(item)
            if doc:
                results.append(doc)
        return results

    def fetch(self, repo_id: str) -> SourceDocument | None:
        """Fetch a single repo by 'owner/repo' string"""
        parts = repo_id.split("/")
        if len(parts) != 2:
            logger.warning(f"Invalid repo_id '{repo_id}' — expected 'owner/repo'")
            return None
        owner, repo = parts

        # Step 1: Get repo info from GitHub API
        repo_data = _github_api_request(f"{GITHUB_API}/repos/{owner}/{repo}")
        if not repo_data:
            # Fallback: try raw README only
            readme = self._fetch_readme(owner, repo)
            if not readme:
                return None
            return SourceDocument(
                id=f"gh:{owner}/{repo}",
                title=f"{owner}/{repo}",
                abstract="GitHub repository (README-only fallback)",
                content=readme,
                source=self.name,
                source_url=f"https://github.com/{owner}/{repo}",
                code_url=f"https://github.com/{owner}/{repo}",
                confidence=0.5,
                metadata={"fallback": True},
            )

        return self._repo_item_to_doc(repo_data)

    def _repo_item_to_doc(self, item: dict) -> SourceDocument | None:
        """Convert GitHub API repo item to SourceDocument"""
        full_name = item.get("full_name", "")
        if not full_name:
            return None

        owner, repo = full_name.split("/", 1)

        # Get README
        readme = self._fetch_readme(owner, repo)

        # Try DeepWiki for architecture summary
        deepwiki = self._fetch_deepwiki(owner, repo)

        # Build content
        content_parts = []
        if deepwiki:
            content_parts.append(f"## DeepWiki Architecture Summary\n\n{deepwiki}\n\n---\n")
        if readme:
            content_parts.append(f"## README\n\n{readme}")
        content = "\n".join(content_parts)

        # Abstract
        desc = item.get("description") or ""
        if deepwiki:
            abstract = f"[DeepWiki] {deepwiki[:300]}"
        else:
            abstract = desc[:300]

        # Tags from topics
        tags = item.get("topics", []) or []

        return SourceDocument(
            id=f"gh:{full_name}",
            title=full_name,
            abstract=abstract or f"GitHub repository: {full_name}",
            content=content,
            source=self.name,
            source_url=item.get("html_url", f"https://github.com/{full_name}"),
            authors=item.get("owner", {}).get("login", ""),
            year=self._extract_year(item),
            tags=tags,
            code_url=item.get("html_url", f"https://github.com/{full_name}"),
            confidence=0.8 if deepwiki else 0.6,
            metadata={
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language", ""),
                "license": (item.get("license") or {}).get("spdx_id", ""),
                "forks": item.get("forks_count", 0),
                "topics": tags,
                "has_deepwiki": bool(deepwiki),
            },
        )

    def _fetch_readme(self, owner: str, repo: str) -> str:
        """Fetch README from raw.githubusercontent.com"""
        for name in ["README.md", "readme.md", "README.rst", "Readme.md"]:
            url = f"{RAW_CONTENT}/{owner}/{repo}/main/{name}"
            content = _fetch_raw(url)
            if content:
                return content
            # Try master branch
            url2 = f"{RAW_CONTENT}/{owner}/{repo}/master/{name}"
            content = _fetch_raw(url2)
            if content:
                return content
        return ""

    def _fetch_deepwiki(self, owner: str, repo: str) -> str:
        """Try to get DeepWiki architecture summary"""
        try:
            url = f"https://deepwiki.ai/api/repo/{owner}/{repo}/summary"
            req = urllib.request.Request(url, headers={"User-Agent": "hfpclawer/0.14.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if isinstance(data, dict):
                    return data.get("summary", data.get("description", ""))
                return str(data)
        except Exception:
            return ""

    @staticmethod
    def _extract_year(item: dict) -> int:
        """Extract year from repo creation date"""
        created = item.get("created_at", "")
        if created and len(created) >= 4:
            try:
                return int(created[:4])
            except ValueError:
                pass
        return 0
