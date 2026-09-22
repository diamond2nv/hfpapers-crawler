#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# item_types.py
"""Item types — a Zotero-shaped vocabulary for what a stored record *is*.

Three axes are kept deliberately apart (rationale and migration notes: `docs/ITEM_TYPE.md`):

* ``item_type`` — the carrier form of the record (journal article? preprint? report?)
* ``venue``     — the container it appeared in (journal / proceedings / repository)
* ``source``    — how it reached this store (provenance: ``import`` / ``cron:<topic>`` / …)

Zotero models the first axis with a closed vocabulary of 38 ``itemType`` values and gives
each type its own field set.  This module adopts Zotero's *names* (so a record maps to
Zotero without translation) but only the subset our adapters can actually distinguish,
plus ``unknown`` for records we refuse to guess about: an honest ``unknown`` is worth more
than a plausible-looking ``journalArticle``.

Nothing here needs the network or the database — derivation is a pure function of the
fields a record already carries, so it is testable and re-runnable (idempotent backfill).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "ItemTypeSpec",
    "ITEM_TYPES",
    "DERIVED_TYPES",
    "derive_item_type",
    "is_peer_reviewed",
    "normalise_item_type",
    "coerce_item_type",
]


@dataclass(frozen=True)
class ItemTypeSpec:
    """One entry of the vocabulary."""

    name: str
    label: str
    peer_reviewed: bool | None  # None = "depends / not meaningful for this type"
    in_zotero: bool = True
    note: str = ""


#: The vocabulary. Ordered by how often we expect each type in this store.
ITEM_TYPES: dict[str, ItemTypeSpec] = {
    "journalArticle": ItemTypeSpec(
        "journalArticle", "Journal article", True, note="Zotero's default for a DOI in a journal."
    ),
    "conferencePaper": ItemTypeSpec(
        "conferencePaper",
        "Conference paper",
        True,
        note="Proceedings / symposium / workshop contributions (Zotero: proceedingsTitle).",
    ),
    "preprint": ItemTypeSpec(
        "preprint",
        "Preprint",
        False,
        note="arXiv and friends — no peer review at the time of the record.",
    ),
    "report": ItemTypeSpec(
        "report",
        "Report / white paper",
        False,
        note="Company technical reports and vendor white papers (Zotero: reportNumber, institution).",
    ),
    "thesis": ItemTypeSpec(
        "thesis", "Thesis / dissertation", False, note="Examined, not peer reviewed (Zotero: university)."
    ),
    "book": ItemTypeSpec("book", "Book", True),
    "bookSection": ItemTypeSpec("bookSection", "Book section", True),
    "dataset": ItemTypeSpec("dataset", "Dataset", False, note="Zotero: a data deposit, e.g. a Zenodo record."),
    "software": ItemTypeSpec(
        "software", "Software", False, note="Code releases — used when the record *is* the artifact."
    ),
    "webpage": ItemTypeSpec("webpage", "Web page", False, note="Blog posts and project pages."),
    "unknown": ItemTypeSpec(
        "unknown",
        "Unknown (not classified)",
        None,
        in_zotero=False,
        note="Our extension: no rule matched, or evidence conflicts. Never a silent default value.",
    ),
}

#: Types this module is willing to assign on its own. ``unknown`` is a *fallback*, not a
#: derivation, so it is excluded — that keeps ``derive_item_type`` honest about coverage.
DERIVED_TYPES = tuple(k for k in ITEM_TYPES if k != "unknown")


# ── Evidence patterns ────────────────────────────────────────────────────────────

# arXiv's own venue spellings, plus the "arXiv (AIIA Lab 精选 …)" style our cron jobs wrote.
_ARXIV_VENUE = re.compile(r"^\s*(arxiv|arxiv \(|cornell university)", re.IGNORECASE)
# An arXiv category accidentally stored as a venue: "physics.plasm-ph", "cs.CL", "cond-mat.mtrl-sci".
_ARXIV_CATEGORY = re.compile(r"^[a-z-]+(\.[A-Za-z-]+)+$")

# Venue keywords for refereed proceedings. Kept as substrings so "Advances in Neural
# Information Processing Systems 38" and "Proc. of the 41st ICML" both match.
_PROCEEDINGS_HINTS = (
    "proceedings",
    "conference",
    "symposium",
    "workshop",
    "advances in neural information processing systems",
    "neurips",
    "nips",
    "icml",
    "iclr",
    "aaai",
    "ijcai",
    "acl",
    "emnlp",
    "naacl",
    "cvpr",
    "iccv",
    "eccv",
    "siggraph",
    "sgp",
    "eurographics",
    "pmlr",
)

_THESIS_HINTS = ("thesis", "dissertation", "habilitation")
_REPORT_VENUE_HINTS = ("technical report", "white paper", "whitepaper", "tech report")
_WEBPAGE_HINTS = ("blog", "blog post", "news", "website", "release notes")
# A venue that says the paper is *not (yet) accepted* outranks any conference acronym in the
# same string: "arXiv:2508.04349 (ICLR 2026 under review)" is a preprint, not an ICLR paper.
# Real example from the store — that record was mis-derived before this rule existed.
_NOT_YET_PUBLISHED_HINTS = (
    "under review",
    "under submission",
    "submitted to",
    "in submission",
    "preprint",
)


def _has(hints: tuple[str, ...], *texts: str) -> str:
    """Return the first hint found in any text, else ``""``.

    Matching is **word-bounded**, not a bare substring search: ``synthesis`` must not fire the
    ``thesis`` marker and ``Oracle`` must not fire ``acl`` (both were real mis-derivations in
    this store before this guard existed).  A hint is allowed to sit next to punctuation or the
    string ends, but not next to another alphanumeric character.
    """
    for text in texts:
        if not text:
            continue
        low = text.lower()
        for hint in hints:
            if re.search(rf"(?<![a-z0-9]){re.escape(hint)}(?![a-z0-9])", low):
                return hint
    return ""


def _looks_like_arxiv_categories(venue: str) -> bool:
    """True when the venue is one or more arXiv categories, e.g. ``cs.LG, physics.plasm-ph``.

    Records whose venue is an arXiv category are preprints that were imported without a
    container title — a comma-separated list of them is still a preprint, not "unknown".
    """
    parts = [p.strip() for p in venue.split(",") if p.strip()]
    return bool(parts) and all(_ARXIV_CATEGORY.match(p) for p in parts)


def derive_item_type(
    *,
    venue: str = "",
    title: str = "",
    id_types: tuple[str, ...] | list[str] = (),
    tags: tuple[str, ...] | list[str] = (),
    has_code: bool = False,
) -> tuple[str, str]:
    """Derive ``(item_type, reason)`` from what a record already carries.

    Pure and ordered: the first matching rule wins, and the reason names the rule and the
    evidence it fired on, so a backfill can be audited line by line.  ``unknown`` means
    "no rule matched" — callers should surface the reason rather than hide it.
    """
    ids = {t.strip().lower() for t in id_types}
    tagset = {t.strip().lower() for t in tags}
    venue_l = (venue or "").strip()

    # 1. Explicit editorial markers beat every naming heuristic.
    if "not-peer-reviewed" in tagset or "non-peer-reviewed" in tagset:
        return "report", "tag:not-peer-reviewed"
    hint = _has(_REPORT_VENUE_HINTS, venue_l)
    if hint:
        return "report", f"venue~{hint}"
    hint = _has(_THESIS_HINTS, venue_l, title)
    if hint:
        return "thesis", f"thesis-marker:{hint}"
    hint = _has(_WEBPAGE_HINTS, venue_l)
    if hint:
        return "webpage", f"venue~{hint}"

    # 2. A venue that states the paper is not accepted yet outranks a conference acronym in the
    #    same string, and so does an arXiv identifier written into the venue.
    hint = _has(_NOT_YET_PUBLISHED_HINTS, venue_l)
    if hint:
        return "preprint", f"venue~{hint}"
    if _ARXIV_VENUE.match(venue_l):
        return "preprint", f"arxiv-venue:{venue_l}"

    # 3. A refereed container named in the venue.
    hint = _has(_PROCEEDINGS_HINTS, venue_l)
    if hint:
        return "conferencePaper", f"venue~{hint}"

    # 4. Preprint repositories: arXiv categories stored as the venue (one, or a comma-separated
    #    list), or an arXiv identifier with no DOI and no journal venue to point at.
    if _looks_like_arxiv_categories(venue_l):
        return "preprint", f"arxiv-category-as-venue:{venue_l[:60]}"
    if "doi" not in ids and venue_l == "" and "arxiv" in ids:
        return "preprint", "no-venue + arxiv-id + no-doi"

    # 5. A DOI plus a named container that is not a preprint server → refereed journal.
    if "doi" in ids and venue_l:
        return "journalArticle", f"doi + venue:{venue_l}"
    if "doi" in ids:
        return "journalArticle", "doi + venue-unknown"

    # 6. Remaining shapes.
    if "arxiv" in ids:
        return "preprint", "arxiv-id only"
    if "url" in ids and not ids & {"doi", "arxiv"}:
        return "webpage", "url-only identifier"

    return "unknown", "no rule matched"


def is_peer_reviewed(item_type: str) -> bool | None:
    """Peer-review status *implied by the carrier form* (``None`` = not decidable)."""
    spec = ITEM_TYPES.get(item_type)
    return spec.peer_reviewed if spec else None


def normalise_item_type(raw: str) -> str:
    """Map loose spellings to the vocabulary (``arXiv`` → ``preprint`` …). Returns ``""``."""
    text = (raw or "").strip()
    if not text:
        return ""
    low = text.lower()
    for name in ITEM_TYPES:
        if low == name.lower():
            return name
    aliases = {
        "journal": "journalArticle",
        "journalarticle": "journalArticle",
        "article": "journalArticle",
        "conference": "conferencePaper",
        "conferencepaper": "conferencePaper",
        "proceedings": "conferencePaper",
        "arxiv": "preprint",
        "arxivpreprint": "preprint",
        "techreport": "report",
        "technicalreport": "report",
        "whitepaper": "report",
        "preprint (non-peer-reviewed)": "report",
        "dissertation": "thesis",
        "bookchapter": "bookSection",
        "code": "software",
        "web": "webpage",
    }
    return aliases.get(re.sub(r"[\s_-]", "", low), "")


def coerce_item_type(raw: str) -> str:
    """Like :func:`normalise_item_type`, but raises on an unknown name (CLI input guard)."""
    name = normalise_item_type(raw)
    if not name:
        raise ValueError(f"unknown item type: {raw!r} (known: {', '.join(ITEM_TYPES)})")
    return name
