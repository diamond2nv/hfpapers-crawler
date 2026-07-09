#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Innovation point extraction — 5-7 structured keywords from paper abstracts.

Uses spaCy to extract key phrases from a paper abstract and classifies them
into semantic slots: Method, Field, Dataset, Metric, Technique, Application,
Core Concept. All heuristic, zero LLM calls, zero tokens.

Designed for:
    - arXiv search query generation (precision recall)
    - Zotero tag suggestions
    - Paper store structured metadata
    - Interest profiling for cron-based new paper monitoring
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from hfpapers.nlp import get_nlp, has_spacy
from hfpapers.nlp.keywords import _is_acronym

logger = logging.getLogger("hfpapers.nlp.innovation")

# ── Innovation point schema ────────────────────────────────────

INNOVATION_SLOTS = [
    "method",       # Core method (PINNs, Fourier Neural Operator, DeepONet)
    "field",        # Research field (PDE, fluid dynamics, quantum)
    "technique",    # Specific technique (spectral convolution, transfer learning)
    "dataset",      # Dataset name (Darcy-2D, ERA5, ImageNet)
    "metric",       # Evaluation metric (relative L2 error, MAE)
    "application",  # Application domain (weather forecasting, crack detection)
    "core_concept", # Core concept (operator learning, neural representation)
]

# Patterns that suggest a method/technique
METHOD_PATTERNS = re.compile(
    r"(neural|network|operator|transformer|attention|kernel|"
    r"graph|convolution|diffusion|generative|adversarial|"
    r"reinforcement|bayesian|variational|autoencoder|"
    r"physics-informed|data-driven|model-based|"
    r"optimization|regularization|approximation)"
)

# Words that are clearly not innovation keywords
NOISE_WORDS = frozenset({
    "study", "paper", "work", "we", "our", "introduction",
    "background", "related", "conclusion", "result", "performance",
    "approach", "method", "framework", "model", "system", "technique",
    "novel", "new", "first", "propose", "proposed", "present",
    "experiment", "experimental", "theoretical", "analysis",
    "investigate", "investigation", "demonstrate", "demonstrated",
    "show", "shows", "shown", "achieve", "achieves",
    "significantly", "state-of-the-art", "sota",
})


def extract_innovation_points(
    abstract: str,
    title: str = "",
) -> dict[str, list[str]]:
    """Extract 5-7 structured innovation keywords from a paper abstract.

    Args:
        abstract: Paper abstract text (plain text).
        title: Optional paper title (used as additional signal).

    Returns:
        Dict mapping slot names to keyword lists:
        {
            "method": ["Fourier Neural Operator"],
            "field": ["parametric PDEs"],
            "technique": ["spectral convolution"],
            "dataset": ["Darcy-2D"],
            "metric": ["relative L2 error"],
            "application": ["fluid dynamics"],
            "core_concept": ["operator learning"],
        }
        Slots with no candidates are omitted.
    """
    if not abstract or not abstract.strip():
        return _fallback_from_title(title)

    nlp = get_nlp()
    if nlp is None:
        return _fallback_from_title(title)

    try:
        doc = nlp(abstract[:3000])  # Limit tokenization cost
    except Exception:
        return _fallback_from_title(title)

    return _extract_with_spacy(doc, title, nlp)


def _extract_with_spacy(
    doc,
    title: str = "",
    nlp=None,
) -> dict[str, list[str]]:
    """Core extraction logic using spaCy annotations."""
    result: dict[str, list[str]] = {slot: [] for slot in INNOVATION_SLOTS}
    seen_phrases: set[str] = set()

    # ── Source 1: Named entities ──
    for ent in doc.ents:
        text = ent.text.strip()
        label = ent.label_
        lower_text = text.lower()

        if len(text) < 2 or lower_text in NOISE_WORDS:
            continue
        # Deduplicate (case-insensitive)
        key = lower_text
        if key in seen_phrases:
            continue
        seen_phrases.add(key)

        # Classify by entity label
        if label in ("ORG", "PRODUCT", "WORK_OF_ART"):
            result["method"].append(text)
        elif label in ("GPE", "LOC"):
            pass  # Not useful for scientific innovation
        elif label in ("EVENT", "LAW"):
            result["technique"].append(text)
        elif label == "DATE":
            pass
        else:
            # PERSON → likely researcher name, skip as innovation point
            pass

    # ── Source 2: Noun chunks + POS patterns ──
    # Score each noun chunk and classify by content
    for chunk in doc.noun_chunks:
        text = chunk.text.strip()
        lower_text = text.lower()

        if len(text) < 3 or lower_text in NOISE_WORDS:
            continue
        if lower_text in seen_phrases:
            continue

        # Check if chunk contains method-indicating words
        has_method_signal = bool(METHOD_PATTERNS.search(lower_text))
        is_acronym = any(_is_acronym(w.text) for w in chunk if w.is_upper)

        # Score: position in abstract + length + acronym bonus
        position_score = 1.0 - (chunk.start / max(len(doc), 1))
        length_bonus = min(len(chunk), 5) / 5.0
        acronym_bonus = 0.3 if is_acronym else 0.0
        method_bonus = 0.2 if has_method_signal else 0.0
        score = position_score * 0.5 + length_bonus * 0.3 + acronym_bonus + method_bonus

        if score < 0.3:
            continue

        seen_phrases.add(lower_text)

        # Classify into slot
        slot = _classify_chunk(text, lower_text, chunk, has_method_signal, is_acronym)
        if slot and len(result[slot]) < 2:
            result[slot].append(text)

    # ── Source 3: Title-based signal ──
    if title:
        title_doc = nlp(title)
        for chunk in title_doc.noun_chunks:
            text = chunk.text.strip()
            lower_text = text.lower()
            if lower_text not in seen_phrases and len(text) > 2:
                seen_phrases.add(lower_text)
                has_method = bool(METHOD_PATTERNS.search(lower_text))
                is_acronym = any(_is_acronym(w.text) for w in chunk if w.is_upper)
                slot = _classify_chunk(
                    text, lower_text, chunk, has_method, is_acronym
                )
                if slot and len(result[slot]) < 2:
                    result[slot].append(text)

    # Flatten: remove empty slots
    return {k: v for k, v in result.items() if v}


def _classify_chunk(
    text: str,
    lower_text: str,
    chunk,
    has_method_signal: bool,
    is_acronym: bool,
) -> Optional[str]:
    """Assign a noun chunk to the most appropriate innovation slot."""
    # Method: acronyms and method-signal words
    if is_acronym:
        return "method"
    if has_method_signal:
        return "method"

    # Dataset: all-caps or numbers+letters
    if re.match(r"^[A-Z0-9\-]+$", text.strip()):
        return "dataset"
    if re.search(r"\d", text) and len(text) < 15:
        return "dataset"

    # Metric: contains "error", "rate", "score", "loss", "accuracy"
    if re.search(r"(error|rate|score|loss|accuracy|metric|mse|mae|rmse|"
                 r"f1|auc|perplexity|bleu)", lower_text):
        return "metric"

    # Technique: contains "method", "technique", "algorithm", "scheme"
    if re.search(r"(technique|algorithm|scheme|protocol|strategy|"
                 r"pipeline|workflow|procedure)", lower_text):
        return "technique"

    # Application: contains "application" or domain words
    if re.search(r"(application|prediction|detection|classification|"
                 r"diagnosis|forecasting|segmentation|recognition)", lower_text):
        return "application"

    # Field: domain keywords at start of chunk
    field_words = {"physics", "chemistry", "biology", "mathematics",
                   "engineering", "medicine", "pde", "fluid", "quantum",
                   "materials", "climate", "weather", "equation",
                   "differential", "mechanics", "dynamics", "optics"}
    if any(fw in lower_text for fw in field_words):
        return "field"

    # Default: core_concept
    return "core_concept"


def _fallback_from_title(title: str) -> dict[str, list[str]]:
    """Fallback: extract innovation-like phrases from title only."""
    if not title:
        return {}
    result: dict[str, list[str]] = {}
    title_lower = title.lower()

    # Check if spaCy is available for basic chunking
    nlp = get_nlp()
    if nlp is not None:
        try:
            doc = nlp(title[:500])
            chunks = sorted(
                [c for c in doc.noun_chunks if len(c.text) > 2],
                key=lambda c: len(c),
                reverse=True,
            )[:5]
            if chunks:
                result["method"] = [c.text for c in chunks[:2]]
                result["core_concept"] = [c.text for c in chunks[2:5]]
                return result
        except Exception:
            pass

    # Pure regex fallback
    words = re.findall(r"[A-Z][a-z]+(?:\s[A-Z][a-z]+)*", title)
    if words:
        result["method"] = words[:3]
    return result


def format_innovation_summary(points: dict[str, list[str]]) -> str:
    """Format innovation points into a human-readable string.

    Args:
        points: Output of ``extract_innovation_points``.

    Returns:
        Brief markdown summary.
    """
    if not points:
        return "*No innovation points extracted*"

    lines = []
    emoji_map = {
        "method": "🔬",
        "field": "📐",
        "technique": "⚙️",
        "dataset": "📊",
        "metric": "📏",
        "application": "🎯",
        "core_concept": "💡",
    }
    for slot in INNOVATION_SLOTS:
        values = points.get(slot, [])
        if values:
            emoji = emoji_map.get(slot, "•")
            label = slot.replace("_", " ").title()
            items = ", ".join(values[:2])
            lines.append(f"  {emoji} **{label}**: {items}")
    return "\n".join(lines)
