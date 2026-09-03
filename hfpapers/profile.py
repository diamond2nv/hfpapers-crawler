#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""profile.py — repo-scoped interest profiles (virtual users) for recommendation.

Real-world usage of hfpclawer spans many repos (stellarator design, control
theory, corpus engineering...), each following DIFFERENT wiki/research topics.
Each repo is effectively a different USER of the paper store. A single global
config.yaml query list cannot serve them all.

Design (repo = virtual user):
- Global baseline: config.yaml search.queries (cross-repo interests, existing).
- Repo profile: a `hfpclawer:` YAML block inside the repo's AGENTS.md
  (Hermes already injects AGENTS.md every session — the interest picture is
  visible to agents for free; hfpclawer parses the same block).
- Fusion: recommend input = global queries ∪ repo queries (repo weights win).

AGENTS.md block convention (mirrors USER.md interest excerpts):

    ## HFPCrawler Interest Profile

    ```yaml
    hfpclawer:
      profile: <repo-topic-slug>
      queries:
        - query: "stellarator permanent magnet design"
          weight: 3
      categories: [fusion, stellarator]
      from_wiki: concepts/digital-twin-plasma-strategy-2026
    ```

Mechanical layer: regex + yaml parse (yaml already a core dep), 0-LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_AGENTS_CANDIDATES = ("AGENTS.md", "agents.md", "AGENT.md")
# REPO_USER.md = repo interest-profile entry (Hermes has no official
# repo-level USER.md; we define one): keeps AGENTS.md a clean dev guide while
# giving the repo's "who uses this repo & for what research" a dedicated file.
_REPO_USER_CANDIDATES = ("REPO_USER.md", "repo_user.md")
_HFPCLAWER_RE = re.compile(r"^hfpclawer:\s*$", re.MULTILINE)


def find_agents_md(start: str | Path | None = None) -> Path | None:
    """Walk up from CWD (or start) to find the nearest AGENTS.md."""
    cur = Path(start or Path.cwd()).resolve()
    if cur.is_file():
        cur = cur.parent
    for d in [cur, *cur.parents]:
        for name in _AGENTS_CANDIDATES:
            p = d / name
            if p.is_file():
                return p
    return None


def find_profile_file(start: str | Path | None = None) -> Path | None:
    """Nearest profile-bearing file: REPO_USER.md preferred, AGENTS.md fallback.

    REPO_USER.md holds the repo's interest picture (who uses this repo, for
    which research); AGENTS.md remains the dev guide — but profiles declared
    in AGENTS.md (older convention) still parse for backward compat.
    """
    cur = Path(start or Path.cwd()).resolve()
    if cur.is_file():
        cur = cur.parent
    for d in [cur, *cur.parents]:
        for name in _REPO_USER_CANDIDATES:
            p = d / name
            if p.is_file() and _HFPCLAWER_RE.search(p.read_text(encoding="utf-8", errors="ignore")):
                return p
        for name in _AGENTS_CANDIDATES:
            p = d / name
            if p.is_file() and _HFPCLAWER_RE.search(p.read_text(encoding="utf-8", errors="ignore")):
                return p
    return None


@dataclass
class RepoProfile:
    """Parsed hfpclawer interest profile from a repo AGENTS.md."""

    profile: str = ""
    queries: list[dict] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    from_wiki: str = ""
    agents_path: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.queries and not self.categories

    def query_tuples(self) -> list[tuple[str, int]]:
        """(query, weight) pairs — default weight 1 when absent.

        Placeholders (angle-bracket templates like <your research keyword>)
        are skipped so an unfilled REPO_USER.md template reads as empty.
        """
        out = []
        for q in self.queries:
            if isinstance(q, dict) and q.get("query"):
                text, w = str(q["query"]), int(q.get("weight", 1) or 1)
            elif isinstance(q, str) and q.strip():
                text, w = q.strip(), 1
            else:
                continue
            if "<" in text or ">" in text:
                continue  # unfilled template placeholder
            out.append((text, w))
        return out


def parse_agents_profile(agents_path: str | Path) -> RepoProfile:
    """Extract the hfpclawer: YAML block from an AGENTS.md.

    Convention: the block sits inside a ```yaml fence and its root key is
    `hfpclawer`. Defensive: returns empty RepoProfile on any parse failure
    (profile must never break repo tooling).
    """
    profile = RepoProfile(agents_path=str(agents_path))
    try:
        text = Path(agents_path).read_text(encoding="utf-8")
    except OSError:
        return profile
    if not _HFPCLAWER_RE.search(text):
        return profile

    # Extract the yaml block containing the hfpclawer: root key
    blocks = re.findall(r"```(?:yaml|yml)\s*\n(.*?)```", text, re.DOTALL)
    for block in blocks:
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict) or "hfpclawer" not in data:
            continue
        h = data["hfpclawer"]
        if not isinstance(h, dict):
            continue
        profile.profile = str(h.get("profile", ""))
        profile.queries = h.get("queries", []) or []
        profile.categories = h.get("categories", []) or []
        profile.from_wiki = str(h.get("from_wiki", ""))
        break
    return profile


def detect_profile(start: str | Path | None = None) -> RepoProfile:
    """Find + parse the nearest repo profile (REPO_USER.md preferred, AGENTS.md fallback)."""
    prof_file = find_profile_file(start)
    if prof_file is None:
        return RepoProfile()
    return parse_agents_profile(prof_file)


# ─── Machine-level (global user) profile — ~/.hfpclawer/profile.yaml ─────────
#
# Real personal interest picture (long-term + ad-hoc research directions that
# span repos) lives OUTSIDE any repo, under the user home:
#   ~/.hfpclawer/profile.yaml
# Never commit real user profiles to repos — hfpapers-crawler is public-facing;
# repo-level AGENTS.md blocks must stay neutral academic keywords only.

def user_profile_dir() -> Path:
    return Path.home() / ".hfpclawer"


def user_profile_path() -> Path:
    return user_profile_dir() / "profile.yaml"


def user_profile() -> RepoProfile:
    """Load ~/.hfpclawer/profile.yaml (empty profile when absent)."""
    p = user_profile_path()
    if not p.exists():
        return RepoProfile(agents_path=str(p))
    prof = RepoProfile(agents_path=str(p))
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return prof
    if not isinstance(data, dict):
        return prof
    h = data.get("hfpclawer", data) if "hfpclawer" in data else data
    if isinstance(h, dict):
        prof.profile = str(h.get("profile", "user"))
        prof.queries = h.get("queries", []) or []
        prof.categories = h.get("categories", []) or []
        prof.from_wiki = str(h.get("from_wiki", ""))
    return prof


def merged_profile(start: str | Path | None = None) -> tuple[RepoProfile, RepoProfile]:
    """(repo_profile, user_profile) — repo wins for repo-scoped commands;
    user profile is the cross-repo machine baseline for global recommend."""
    return detect_profile(start), user_profile()
