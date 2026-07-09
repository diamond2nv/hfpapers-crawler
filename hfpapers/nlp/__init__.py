#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hfpapers.nlp — spaCy-enhanced NLP toolkit for hfpclawer.

All spaCy imports are lazy. The module degrades gracefully when spaCy
or the language model is not installed — all public functions return
the standard (non-NLP-enhanced) result as fallback.

Features:
    - Enhanced title keyword extraction (lemmatization, noun chunks)
    - Semantic similarity reranking (word vectors for borderline matches)
    - Innovation point extraction (5-7 key phrases from abstracts)
    - Auto-tag generation (NER + noun chunks → Zotero tags)
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("hfpapers.nlp")

# ── Lazy spaCy loader ──────────────────────────────────────────

_SPACY_MODEL: str | None = (
    None  # Set via configure(model="en_core_web_md")
)
_NLP_INSTANCE = None  # Cached spaCy Language object


def configure(model: str = "en_core_web_md") -> bool:
    """Configure and load the spaCy model.

    Call once at application startup (e.g., in CLI init).
    Sets the model path globally. Returns True if model loaded, False if unavailable.

    Args:
        model: spaCy pipeline package name.
    """
    global _SPACY_MODEL
    _SPACY_MODEL = model
    result = _load_spacy()
    if result is not None:
        logger.info("spaCy loaded: %s (%.1f MB)", model, _model_mb(result))
        return True
    return False


def _model_mb(nlp) -> float:
    try:
        import os
        total = 0
        for name in nlp.component_names:
            comp = nlp.get_pipe(name)
            if hasattr(comp, "model") and hasattr(comp.model, "path"):
                p = comp.model.path
                if os.path.isdir(p):
                    for dirpath, _, fnames in os.walk(p):
                        for fn in fnames:
                            fp = os.path.join(dirpath, fn)
                            if os.path.isfile(fp):
                                total += os.path.getsize(fp)
        return total / (1024 * 1024)
    except Exception:
        return 0.0


def _load_spacy() -> Optional[object]:
    """Get the spaCy Language object, loading if necessary.

    Returns None if spaCy or model is unavailable.
    """
    global _NLP_INSTANCE, _SPACY_MODEL
    if _NLP_INSTANCE is not None:
        return _NLP_INSTANCE
    model = _SPACY_MODEL or "en_core_web_md"
    try:
        import spacy
        _NLP_INSTANCE = spacy.load(model)
        return _NLP_INSTANCE
    except ImportError:
        logger.debug("spaCy not installed — NLP features disabled")
        return None
    except OSError:
        logger.debug("spaCy model '%s' not found — download with: python -m spacy download %s", model, model)
        return None


def get_nlp() -> Optional[object]:
    """Return the cached spaCy Language object, or None if unavailable."""
    if _NLP_INSTANCE is not None:
        return _NLP_INSTANCE
    return _load_spacy()


def has_spacy() -> bool:
    """Check if spaCy with model is available."""
    return get_nlp() is not None
