#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enhanced title keyword extraction with spaCy lemmatization + noun chunks.

Provides drop-in replacements for the current regex+stopword approach
in ``hfpclawer.zotero.zotero_client.ZoteroClient._title_keywords``.

Degrades gracefully: returns standard output when spaCy is unavailable.
"""

from __future__ import annotations

import logging
import re

from hfpapers.nlp import get_nlp

logger = logging.getLogger("hfpapers.nlp.keywords")

# ── Stopword sets ──────────────────────────────────────────────

# Core stopwords (lightweight, always applied)
CORE_STOPWORDS = frozenset({
    "a", "an", "the", "this", "that", "these", "those",
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "can", "could", "shall", "should", "may", "might", "must",
    "of", "in", "on", "at", "by", "for", "with", "about", "against",
    "between", "into", "through", "during", "before", "after",
    "above", "below", "to", "from", "up", "down", "out", "off",
    "over", "under", "again", "further", "then", "once",
    "here", "there", "when", "where", "why", "how",
    "all", "each", "every", "both", "few", "more", "most",
    "other", "some", "such", "no", "not", "only", "own",
    "same", "so", "than", "too", "very", "just", "because", "as",
    "until", "while", "of", "based", "using",
    # Scientific context stopwords
    "novel", "new", "approach", "method", "toward", "towards",
    "study", "paper", "work", "we", "our", "propose", "proposed",
    "introduce", "introduced", "present", "presented",
    "show", "shows", "shown", "demonstrate", "demonstrates",
    "demonstrated", "achieve", "achieves", "achieved",
    "improve", "improves", "improved", "efficient",
    "effective", "novel", "first", "via",
})

# Words to always keep as-is (acronyms, technical terms)
ACRONYM_PATTERN = re.compile(r"^[A-Z0-9]{2,6}$")


def _is_acronym(word: str) -> bool:
    """Check if a word looks like an acronym (e.g., PINN, PDE, FNO, LCLM)."""
    return bool(ACRONYM_PATTERN.match(word)) and word.isupper()


def extract_keywords_enhanced(
    title: str,
    max_words: int = 6,
    include_noun_chunks: bool = True,
) -> str:
    """Extract meaningful keywords from a paper title.

    Uses spaCy for lemmatization + noun chunks when available.
    Falls back to enhanced regex-based extraction otherwise.

    Compared to the current ``_title_keywords``:
      - ``training`` → ``train`` (lemmatization)
      - ``networks`` → ``network`` (lemmatization)
      - ``physics-informed neural networks`` → kept as phrase (noun chunk)

    Args:
        title: Paper title string.
        max_words: Maximum number of words/phrases to return.
        include_noun_chunks: If True, prefer noun chunks over single words.

    Returns:
        Space-separated keyword string, suitable for Zotero FTS query.
    """
    if not title or not title.strip():
        return ""

    nlp = get_nlp()
    if nlp is not None:
        return _extract_with_spacy(nlp, title, max_words, include_noun_chunks)
    return _extract_fallback(title, max_words)


def _extract_with_spacy(
    nlp,
    title: str,
    max_words: int = 6,
    include_noun_chunks: bool = True,
) -> str:
    """Extract keywords using spaCy."""
    doc = nlp(title)

    # Strategy 1: Collect meaningful tokens (lemma + filter stopwords)
    lemmatized = []
    for token in doc:
        t = token.text
        l = token.lemma_

        # Keep acronyms as original
        if _is_acronym(t):
            lemmatized.append(t)
            continue

        # Skip stopwords, punctuation, spaces
        if token.is_stop or token.is_punct or token.is_space or token.is_digit:
            continue
        if token.pos_ in ("DET", "ADP", "CCONJ", "SCONJ", "PRON", "PART"):
            continue

        # Use lemma, but keep casing if it's a proper noun
        lemma = l if token.pos_ != "PROPN" else t
        if len(lemma) > 1:
            lemmatized.append(lemma.lower())

    # Strategy 2: Extract meaningful noun chunks (preferred)
    if include_noun_chunks:
        chunks = []
        for chunk in doc.noun_chunks:
            # Filter out chunks that are entirely stopwords
            content_words = [w for w in chunk if not w.is_stop and not w.is_punct and w.pos_ not in ("DET", "ADP")]
            if content_words:
                chunk_text = " ".join(
                    w.lemma_.lower() if w.pos_ != "PROPN" else w.text
                    for w in content_words
                    if len(w.text) > 1
                )
                # Deduplicate at phrase level
                if chunk_text and chunk_text not in chunks:
                    chunks.append(chunk_text)

        # Merge: noun chunks first, then individual lemmas to fill up
        result = chunks[:max_words]
        if len(result) < max_words:
            seen_phrases = set(chunks)
            for w in lemmatized:
                if w not in seen_phrases:
                    result.append(w)
                    seen_phrases.add(w)
                    if len(result) >= max_words:
                        break

        return " ".join(result[:max_words])

    # Fallback: just lemma words
    seen = set()
    unique = []
    for w in lemmatized:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return " ".join(unique[:max_words])


def _extract_fallback(title: str, max_words: int = 6) -> str:
    """Enhanced regex-based fallback when spaCy unavailable.

    Improved over the current ``_title_keywords``:
      - Basic suffix stripping for common English verb/noun forms
      - Better acronym detection
    """
    words = re.sub(r"[^\w\s-]", " ", title).split()

    filtered: list[str] = []
    for w in words:
        if len(w) <= 1:
            continue
        wl = w.lower()
        if wl in CORE_STOPWORDS:
            continue
        if _is_acronym(w):
            filtered.append(w.upper())
        else:
            # Basic suffix stripping (heuristic)
            stripped = _basic_stem(wl)
            filtered.append(stripped)

    seen = set()
    unique = []
    for w in filtered:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return " ".join(unique[:max_words])


def _basic_stem(word: str) -> str:
    """Lightweight suffix stripping for English words.

    Covers the most common verb forms to reduce variability in keyword matching.
    Not a replacement for proper lemmatization, but better than nothing.
    """
    w = word
    # -ing → (training→train, solving→solv...keeping→keep)
    if w.endswith("ing") and len(w) > 5:
        base = w[:-3]
        if base.endswith("nn") or base.endswith("tt"):
            base = base[:-1]
        if len(base) > 2:
            return base
        return w
    # -ed → (trained→train, solved→solv, based→base)
    if w.endswith("ed") and len(w) > 4:
        base = w[:-2]
        if base.endswith("i"):
            base = base[:-1] + "y"
        if len(base) > 2:
            return base
        return w
    # -s → (networks→network, solvers→solver) — but not -ss, not 'is'
    if w.endswith("s") and not w.endswith("ss") and len(w) > 4:
        base = w[:-1]
        if len(base) > 2:
            return base
    # -tion → -te (optimization→optimizate — imperfect but better)
    if w.endswith("tion") and len(w) > 6:
        return w[:-4] + "te"
    return w


# ── Convenience aliases for drop-in replacement ────────────────

def title_keywords(title: str, max_words: int = 6) -> str:
    """Drop-in replacement for ``ZoteroClient._title_keywords``.

    Usage in existing code:
        from hfpapers.nlp.keywords import title_keywords
        keywords = title_keywords("A novel approach to neural PDE solvers")
        # → "neural pde solver"  (with spaCy)
        # → "neural pde solvers"  (fallback)
    """
    return extract_keywords_enhanced(title, max_words=max_words)
