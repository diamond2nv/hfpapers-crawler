#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Auto-tag generation for Zotero items using spaCy.

Generates structured tags from paper title + abstract:
  - Entity tags: methods, datasets, organizations (from NER)
  - Topic tags: research field, technique (from noun chunks)
  - Acronym tags: common abbreviations (PINN, FNO, PDE, etc.)

Output tags are designed for Zotero's tag system and can be written
via the Connector protocol (POST /connector/saveItems).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from hfpapers.nlp import get_nlp, has_spacy
from hfpapers.nlp.keywords import _is_acronym

logger = logging.getLogger("hfpapers.nlp.tags")

# ── Configuration ──────────────────────────────────────────────

# Maximum auto-generated tags per paper
MAX_TAGS = 15

# Minimum length for a content word tag
MIN_TAG_LENGTH = 3

# Domain tag mappings (lowercase source → tag)
DOMAIN_TAGS = {
    "pde": "PDE",
    "partial differential equation": "PDE",
    "neural operator": "Neural-Operator",
    "operator learning": "Operator-Learning",
    "physics-informed": "Physics-Informed",
    "deep learning": "Deep-Learning",
    "machine learning": "Machine-Learning",
    "reinforcement learning": "Reinforcement-Learning",
    "transformers": "Transformer",
    "attention": "Attention",
    "graph neural": "Graph-Neural-Network",
    "gnn": "Graph-Neural-Network",
    "convolutional": "CNN",
    "generative": "Generative-Model",
    "diffusion": "Diffusion-Model",
    "mfl": "MFL",
    "magnetic flux leakage": "MFL",
    "finite element": "FEM",
    "finite difference": "FDM",
    "boundary element": "BEM",
    "monte carlo": "Monte-Carlo",
    "optimization": "Optimization",
    "bayesian": "Bayesian",
    "variational": "Variational",
    "autoencoder": "Autoencoder",
    "representation learning": "Representation-Learning",
    "transfer learning": "Transfer-Learning",
    "meta learning": "Meta-Learning",
    "few-shot": "Few-Shot",
    "zero-shot": "Zero-Shot",
    "multimodal": "MultiModal",
    "computer vision": "Computer-Vision",
    "natural language": "NLP",
    "nlp": "NLP",
    "quantum": "Quantum",
    "causal": "Causal-Inference",
    "symbolic": "Symbolic",
    "scientific computing": "Scientific-Computing",
}


def generate_tags(
    title: str,
    abstract: str = "",
    nlp=None,
) -> list[str]:
    """Generate auto-tags for a paper from its title and abstract.

    Uses spaCy when available for NER + noun chunk extraction.

    Args:
        title: Paper title.
        abstract: Paper abstract (optional, improves tag quality).
        nlp: Pre-loaded spaCy Language object (lazy-loaded if None).

    Returns:
        Sorted list of tag strings, e.g.:
        ["PDE", "Fourier-Neural-Operator", "Operator-Learning", ...]
    """
    tags: set[str] = set()
    text = f"{title}. {abstract}" if abstract else title

    if nlp is None:
        nlp = get_nlp()

    if nlp is not None:
        tags |= _extract_tags_with_spacy(nlp, text, title)

    # Always add domain-based tags from keyword matching
    tags |= _extract_domain_tags(text)

    # Always add acronym tags
    tags |= _extract_acronym_tags(text)

    # Sort and limit
    sorted_tags = sorted(tags, key=lambda t: (-len(t), t))
    return sorted_tags[:MAX_TAGS]


def _extract_tags_with_spacy(nlp, text: str, title: str) -> set[str]:
    """Extract tags from spaCy annotations."""
    tags: set[str] = set()
    doc = nlp(text[:2000])  # Limit processing cost

    # ── Entity-based tags ──
    for ent in doc.ents:
        ent_text = ent.text.strip()
        if len(ent_text) < MIN_TAG_LENGTH:
            continue

        # Skip common uninformative entities
        if ent_text.lower() in {"et al.", "et al", "figure", "table", "section"}:
            continue

        # Keep ORG and PRODUCT as tags
        if ent.label_ in ("ORG", "PRODUCT", "WORK_OF_ART"):
            tag = _normalize_tag(ent_text)
            if tag:
                tags.add(tag)

    # ── Noun chunk tags ──
    seen_chunks: set[str] = set()
    for chunk in doc.noun_chunks:
        text_lower = chunk.text.lower().strip()
        if len(chunk.text) < MIN_TAG_LENGTH:
            continue

        # Skip stopword-only chunks
        content = [w for w in chunk if not w.is_stop]
        if not content:
            continue

        # Deduplicate
        key = text_lower
        if key in seen_chunks:
            continue
        seen_chunks.add(key)

        # Tag-worthy: has content words + length > 2
        chunk_tag = _select_tagworthy_chunk(chunk)
        if chunk_tag:
            tags.add(chunk_tag)

    # ── Title-specific: extract proper noun sequences ──
    title_doc = nlp(title[:300])
    title_acronyms = _extract_acronym_tags(title)
    tags.update(title_acronyms)

    # Title first noun chunk as primary tag
    for chunk in title_doc.noun_chunks:
        tag = _normalize_tag(chunk.text.strip())
        if tag and len(tag) > 2:
            tags.add(tag)
            break  # Just the first meaningful chunk from title

    return tags


def _select_tagworthy_chunk(chunk) -> Optional[str]:
    """Determine if a noun chunk makes a good tag, and normalize it."""
    words = [w for w in chunk if not w.is_stop and not w.is_punct]
    if not words:
        return None

    # Build tag from content words
    tag_parts: list[str] = []
    for w in words[:4]:  # max 4 words
        if len(w.text) < MIN_TAG_LENGTH and not _is_acronym(w.text):
            continue
        # For proper nouns, keep original case; otherwise capitalize
        if w.pos_ == "PROPN" or _is_acronym(w.text):
            tag_parts.append(w.text)
        else:
            tag_parts.append(w.text.capitalize())

    if not tag_parts:
        return None
    tag = "-".join(tag_parts)
    if len(tag) < MIN_TAG_LENGTH:
        return None
    return tag


def _extract_domain_tags(text: str) -> set[str]:
    """Match domain patterns and return normalized tags."""
    tags: set[str] = set()
    lower = text.lower()
    for pattern, tag in DOMAIN_TAGS.items():
        if pattern in lower:
            tags.add(tag)
    return tags


def _extract_acronym_tags(text: str) -> set[str]:
    """Extract acronyms (2-6 uppercase letters that aren't common words)."""
    tags: set[str] = set()
    # Find candidate acronyms
    acronyms = re.findall(r"\b([A-Z]{2,6})\b", text)
    common_uppercase = {"THE", "THIS", "THAT", "FROM", "WITH", "THAN",
                        "OUR", "ALL", "CAN", "MAY", "WILL", "HAVE",
                        "HAS", "HAD", "ARE", "WAS", "WERE", "BEEN",
                        "MUST", "SHALL", "COULD", "SHOULD", "ABOUT",
                        "BETWEEN", "THROUGH", "DURING", "BEFORE",
                        "AFTER", "ABOVE", "BELOW", "AGAIN", "THEN",
                        "ONCE", "HERE", "THERE", "WHEN", "WHERE",
                        "WHY", "HOW", "MORE", "MOST", "OTHER", "SOME",
                        "SUCH", "SAME", "SOON", "PART", "DATA", "USED",
                        "BASED", "FIRST", "LEVEL", "ETC", "ALSO", "ONE",
                        "TWO", "FIG", "TABLE", "STEP", "TYPE", "SET"}

    for acronym in acronyms:
        if acronym not in common_uppercase:
            tags.add(acronym)
    return tags


def _normalize_tag(text: str) -> Optional[str]:
    """Normalize a tag string for Zotero.

    Replaces spaces with hyphens, strips leading/trailing noise.
    Caps at ~40 characters to keep tags concise.
    """
    text = text.strip().strip(".,;:!?\"'()[]{}")
    if len(text) < MIN_TAG_LENGTH:
        return None
    # Remove leading/trailing stopwords
    words = text.split()
    while words and words[0].lower() in {"the", "a", "an", "this", "that", "these", "those"}:
        words.pop(0)
    while words and words[-1].lower() in {"the", "a", "an", "of", "in", "for", "and", "or"}:
        words.pop()
    if not words:
        return None
    text = "-".join(words)
    # Cap length
    if len(text) > 45:
        text = text[:42] + "..."
    return text
