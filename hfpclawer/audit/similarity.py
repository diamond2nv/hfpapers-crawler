#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Title normalization and similarity scoring utilities.

Merged from:
  - hfpclawer._text_similarity (CC BY-NC 4.0, Cheng-I Wu)
  - coc.references.verify._normalise_title (Hermes Agent)
"""

import re
from difflib import SequenceMatcher


def normalize_title(title: str) -> str:
    """Normalize a paper title for comparison.

    Removes LaTeX commands, punctuation, collapses whitespace, lowercase.
    """
    s = title.strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[{}]", "", s)
    s = re.sub(r"\\(?:text|mathrm|textbf|mathit|emph|textit)\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\(?:[a-z]+)(?:\{[^}]*\})?", "", s)
    s = re.sub(r"[^a-z0-9\s]", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def title_similarity(a: str, b: str) -> float:
    """Return SequenceMatcher ratio in [0, 1] between two normalized titles."""
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def exact_match(a: str, b: str) -> bool:
    """Return True if normalized titles are identical."""
    return normalize_title(a) == normalize_title(b)


# Alias for backward compatibility
_normalize_title = normalize_title
