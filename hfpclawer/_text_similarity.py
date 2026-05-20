#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Title normalization and similarity scoring utilities.

Adapted from academic-research-skills by Cheng-I Wu
(https://github.com/Imbad0202/academic-research-skills)
Licensed under CC BY-NC 4.0
"""

import re
from difflib import SequenceMatcher


def _normalize_title(title: str) -> str:
    """Normalize a paper title for comparison: lowercase, strip punctuation,
    collapse whitespace."""
    cleaned = re.sub(r"[^\w\s]", "", title)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip().lower()


def title_similarity(a: str, b: str) -> float:
    """Normalize two titles and return SequenceMatcher ratio in [0, 1]."""
    return SequenceMatcher(None, _normalize_title(a), _normalize_title(b)).ratio()


def exact_match(a: str, b: str) -> bool:
    """Return True if normalized titles are identical."""
    return _normalize_title(a) == _normalize_title(b)
