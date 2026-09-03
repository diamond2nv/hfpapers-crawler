#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recommend.py — first-party paper recommendation (roadmap §2b/§2d, L0+L1).

Signals (all local, 0 external dependency):
  L0 global   config.yaml search.queries      (cross-repo baseline)
  L0b machine ~/.hfpclawer/profile.yaml       (user profile — real interests)
  L1 repo     REPO_USER.md / AGENTS.md block  (repo = virtual user)
Fusion: per-query weight × paper relevance, summed per paper; repo-layer
weights beat global on tie. Verification gate (v0.16 state machine):
suspect never recommended, stale down-weighted, verified preferred.
Every result carries `why` = (layer, query) hits — auditable by design.
"""

from __future__ import annotations

from pathlib import Path

from hfpapers.profile import detect_profile, user_profile

DEFAULT_RELEVANCE = 50  # unscored papers (relevance=0) treated as mid


def _config_queries() -> list[tuple[str, int, str]]:
    """Global baseline from config.yaml search.queries."""
    try:
        from hfpapers.config import get

        qs = get("search.queries", []) or []
    except Exception:
        return []
    out = []
    for q in qs:
        if isinstance(q, dict) and q.get("query"):
            out.append((str(q["query"]), int(q.get("weight", 1) or 1), "global"))
        elif isinstance(q, str) and q.strip():
            out.append((q.strip(), 1, "global"))
    return out


def build_query_pool(repo_dir: str | Path | None = None) -> list[tuple[str, int, str]]:
    """(query, weight, layer) pool: global ∪ repo ∪ user; repo wins ties.

    Dedup by query text — same query from multiple layers keeps the
    highest-priority layer (repo > user > global) with its weight.
    """
    pool: dict[str, tuple[int, str]] = {}
    for q, w, layer in _config_queries():
        pool.setdefault(q.lower(), (w, layer))

    repo = detect_profile(repo_dir)
    for q, w in repo.query_tuples():
        pool[q.lower()] = (w, "repo")

    user = user_profile()
    for q, w in user.query_tuples():
        cur = pool.get(q.lower())
        if cur is None or cur[1] == "global":
            pool[q.lower()] = (w, "user")

    return [(q, w, layer) for q, (w, layer) in pool.items()]


def recommend(
    store,
    limit: int = 10,
    repo_dir: str | Path | None = None,
    status_gate: bool = True,
    stale_penalty: float = 0.5,
    per_query: int = 30,
) -> list[dict]:
    """Top-N papers from the fused query pool, gated by verification state.

    Returns [{sf_id, title, score, status, why: [(layer, query), ...]}].
    """
    pool = build_query_pool(repo_dir)
    if not pool:
        return []

    scores: dict[int, float] = {}
    why: dict[int, list[tuple[str, str]]] = {}
    for q, w, layer in pool:
        try:
            papers = store.search_papers(q, limit=per_query)
        except Exception:
            continue
        for p in papers:
            rel = p.relevance if getattr(p, "relevance", 0) else DEFAULT_RELEVANCE
            base = max(rel, 1) / 100.0
            scores[p.sf_id] = scores.get(p.sf_id, 0.0) + w * base
            hits = why.setdefault(p.sf_id, [])
            if len(hits) < 3:  # keep why compact (top-3 query hits)
                hits.append((layer, q))

    if status_gate:
        for sf_id in list(scores):
            st = store.get_status(sf_id)
            status = st["status"]
            if status == "suspect":
                del scores[sf_id]  # suspect never recommended
                why.pop(sf_id, None)
            elif status == "stale":
                scores[sf_id] *= stale_penalty
            elif status == "unknown":
                del scores[sf_id]
                why.pop(sf_id, None)

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:limit]
    out = []
    for sf_id, score in ranked:
        rec = store.get_paper_by_id(sf_id)
        st = store.get_status(sf_id)
        out.append(
            {
                "sf_id": sf_id,
                "title": (rec.title if rec else "")[:120],
                "score": round(score, 4),
                "status": st["status"],
                "why": why.get(sf_id, []),
            }
        )
    return out
