#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Semantic similarity reranking for Zotero search results.

Adds a middle layer (L1b) between the current fast keyword FTS and
the slow full-scan fallback. Uses spaCy word vectors to rerank
borderline SequenceMatcher matches — capturing semantic equivalents
like "PINNs" ↔ "Physics-Informed Neural Networks" or
"FEM" ↔ "Finite Element Method".

Degrades gracefully when spaCy or word vectors are unavailable.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher

from hfpapers.nlp import get_nlp

logger = logging.getLogger("hfpapers.nlp.search")

# ── Similarity thresholds ──────────────────────────────────────

# SequenceMatcher ratio above this → direct acceptance (no spaCy needed)
HIGH_CONFIDENCE = 0.80

# SequenceMatcher ratio below this → skip (too different even for vectors)
LOW_CONFIDENCE = 0.30

# SequenceMatcher ratio in this range → try vector reranking
VEC_RERANK_MIN = 0.30
VEC_RERANK_MAX = 0.80


def semantic_rerank(
    query_title: str,
    candidate_title: str,
    seq_sim: float,
) -> float:
    """Rerank a title pair using spaCy word vectors when SequenceMatcher is borderline.

    Args:
        query_title: The title being searched for.
        candidate_title: A candidate title from Zotero.
        seq_sim: Pre-computed SequenceMatcher ratio for this pair.

    Returns:
        A similarity score in [0, 1]. When spaCy vectors are unavailable
        or the pair is outside the rerank window, returns seq_sim unchanged.
    """
    # Outside rerank window → return original score
    if seq_sim >= HIGH_CONFIDENCE or seq_sim < LOW_CONFIDENCE:
        return seq_sim

    nlp = get_nlp()
    if nlp is None:
        return seq_sim

    try:
        q_doc = nlp(query_title)
        c_doc = nlp(candidate_title)

        # Check that both have vectors (sm model doesn't ship word vectors)
        if not q_doc.has_vector or not c_doc.has_vector:
            return seq_sim

        vec_sim = q_doc.similarity(c_doc)

        # Blend: weighted average favoring the higher score
        # This means: if vectors strongly agree, bump the score up
        blended = max(seq_sim, vec_sim * 0.9 + seq_sim * 0.1)

        logger.debug(
            "rerank: seq=%.3f vec=%.3f blended=%.3f | %s vs %s",
            seq_sim, vec_sim, blended,
            query_title[:40], candidate_title[:40],
        )
        return blended

    except Exception:
        logger.debug("vector rerank failed, using seq=%.3f", seq_sim, exc_info=True)
        return seq_sim


def hybrid_match_score(
    query_title: str,
    candidate_title: str,
) -> float:
    """Compute a hybrid match score between two titles.

    Combination of:
      1. SequenceMatcher (fast, character-level)
      2. spaCy vector similarity (semantic, if available and borderline)

    Returns a score in [0, 1].
    """
    q = query_title.lower()
    c = candidate_title.lower()
    seq = SequenceMatcher(None, q, c).ratio()
    return semantic_rerank(query_title, candidate_title, seq)


def filter_by_similarity(
    query_title: str,
    candidates: list[dict],
    min_score: float = 0.55,
    title_field: str = "title",
) -> list[tuple[float, dict]]:
    """Filter and score a list of candidate Zotero items by title similarity.

    Uses hybrid matching (SequenceMatcher + optional vector rerank).

    Args:
        query_title: Search title.
        candidates: List of Zotero item dicts.
        min_score: Minimum similarity to include in results.
        title_field: Key for the title in the item dict's ``data`` sub-dict.

    Returns:
        List of (score, item) tuples sorted by score descending.
    """
    scored: list[tuple[float, dict]] = []
    for item in candidates:
        data = item.get("data", {}) or {}
        item_title = data.get(title_field, "")
        if not item_title:
            continue
        score = hybrid_match_score(query_title, item_title)
        if score >= min_score:
            scored.append((score, item))

    scored.sort(key=lambda x: -x[0])
    return scored
