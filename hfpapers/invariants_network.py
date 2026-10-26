#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# invariants_network.py
"""The one expensive invariant: does each DOI actually point at this paper?

Split out of `invariants.py` so the offline checks stay import-free and instant — a gate that needs
the network is not a gate.  Called only with `network=True`; failures to reach Crossref are counted
separately from findings, because "could not check" is not "wrong" (the live pass had 0 unreachable,
so the distinction is cheap to keep).

The comparison is deliberately blunt: normalise both titles, require a similarity above
``MATCH_THRESHOLD``, and report anything below as an error — *not* as a decision to delete.  Two of
the live store's wrong DOIs scored 0.79, so a threshold alone is not a verdict; it is a triage.

Two normalisation rules exist because the ratio, computed the naive way, called *correct* DOIs
wrong (live store, 2026-09-25):

- **Inline markup is stripped first.**  Crossref titles carry MathML/XML inline
  (``High-<mml:math …>β</mml:math>Equilibria …``).  Collapsing those tags into the character
  budget spent it on markup: ``10.1103/PhysRevLett.89.125003`` scored **0.165**, and **0.957**
  once the tags are dropped.  Truncating to the first 80 characters only rescued titles whose
  markup sits at the *end* (``10.1103/physrevd.105.032001``), which is how the same defect
  deleted a correct DOI in a peer's audit.
- **Cross-language pairs are counted, never scored.**  A CJK record compared against the English
  title Crossref holds (``物理学报`` → its English translation) scores 0.00 — the number measures
  the comparison method, not the data.  Those pairs are skipped and reported as a count, because
  a "mismatch" here is an instruction to delete a Chinese journal paper.
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import time
import unicodedata
from typing import Any, Iterable

from hfpapers.invariants import Finding, InvariantReport, is_cross_language, strip_inline_markup

MATCH_THRESHOLD = 0.62
_CROSSREF = "https://api.crossref.org/works/"
_UA = "hfpclawer (mailto:dev@example.com)"


def _norm(text: str) -> str:
    """Normalise a title for comparison — markup first, then case/punctuation, then truncate."""
    text = unicodedata.normalize("NFKC", strip_inline_markup(text or "")).lower()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)[:80]


def doi_title_pair(doi: str, title: str, timeout: int = 25) -> tuple[bool | None, str]:
    """``(does ``doi`` describe ``title``, the title the registry holds)``.

    Uses the write path's resolver — Crossref, then DataCite — so the audit, `store dedup` and the
    write gate cannot disagree about what a DOI points at.  ``None`` means no registry answered (or a
    cross-language pair, which a character ratio cannot judge); the registry title is returned either
    way so a caller can name what the DOI *does* point at when it disagrees.
    """

    from hfpapers.doi_registry import resolve

    status, work = resolve(doi, timeout=timeout)
    registry_title = str((work or {}).get("title", ""))
    if status != "ok" or not registry_title or not title or is_cross_language(title, registry_title):
        return None, registry_title
    ratio = difflib.SequenceMatcher(None, _norm(title), _norm(registry_title)).ratio()
    return ratio >= MATCH_THRESHOLD, registry_title


def doi_matches_title(doi: str, title: str, timeout: int = 25) -> bool | None:
    """Does ``doi`` describe ``title``?  ``None`` when no registry could answer.

    Title comparison reuses this module's normalisation, and a cross-language pair returns ``None``: a
    character ratio cannot judge a CJK record against the English title Crossref holds.
    """

    return doi_title_pair(doi, title, timeout=timeout)[0]


def refine_duplicate_findings(
    report: InvariantReport, store: Any, *, timeout: int = 25
) -> tuple[int, int]:
    """Re-judge duplicate findings with each record's own DOI; returns ``(groups, DOIs checked)``.

    Offline a duplicate is an error for every member of the group.  Whether it is a defect depends on
    the DOIs, which only a registry can settle: two artefacts of one work are a legitimate pair (both
    become ``info``), while a copy whose DOI describes another paper is a defect with a named culprit
    (that member stays ``error``, the keeper becomes ``info``).  Without network evidence the findings
    are left exactly as they were — an unanswered question is not a verdict.
    """

    from hfpapers.invariants import DuplicateMember, plan_duplicate_group

    groups: dict[tuple[int, ...], int] = {}
    for finding in report.findings:
        if finding.check not in ("record.duplicate_identity", "record.title_collision"):
            continue
        members = tuple(sorted((finding.evidence or {}).get("group") or []))
        if members:
            groups[members] = groups.get(members, 0) + 1

    verdicts: dict[int, tuple[str, str]] = {}
    checked = 0
    for members in groups:
        payload: list[DuplicateMember] = []
        titles: dict[int, str] = {}
        for sf_id in members:
            paper = store.get_paper_by_id(sf_id)
            if not paper:
                continue
            ids = store.get_identifiers(sf_id) or []
            doi = next((i.id_value for i in ids if i.id_type == "doi"), "")
            matches = doi_matches_title(doi, paper.title or "", timeout=timeout) if doi else None
            checked += 1 if doi else 0
            titles[sf_id] = paper.title or ""
            payload.append(
                DuplicateMember(
                    int(sf_id), paper.title or "", int(paper.year or 0),
                    frozenset(i.id_type for i in ids), matches,
                )
            )
        keep, drops = plan_duplicate_group(payload)
        if keep is None:
            continue
        for member, verdict in drops:
            verdicts[member.sf_id] = (verdict, titles.get(keep.sf_id, ""))
        verdicts.setdefault(keep.sf_id, ("kept" if drops else "single", ""))

    for finding in report.findings:
        if finding.check not in ("record.duplicate_identity", "record.title_collision"):
            continue
        try:
            sf_id = int(finding.subject)
        except (TypeError, ValueError):
            continue
        verdict, keeper_title = verdicts.get(sf_id, ("human", ""))
        if verdict == "version_pair":
            finding.check = "record.version_pair"
            finding.severity = "info"
            finding.detail = (
                "two artefacts of one work: each record's DOI describes this title (journal paper and "
                "report); both kept deliberately"
            )
        elif verdict == "drop_wrong_doi":
            finding.severity = "error"
            finding.detail = (
                f"this copy's DOI describes a different paper, while {keeper_title[:60]!r} holds the "
                "correct one — duplicate of the keeper, and its DOI must be discarded, not moved"
            )
        elif verdict in ("mergeable", "kept"):
            finding.severity = "info" if verdict == "kept" else finding.severity

    return len(groups), checked


def _crossref_title(doi: str, timeout: int = 25) -> str | None:
    """Return the title Crossref has for ``doi``, or ``None`` when unreachable/unknown."""
    url = _CROSSREF + doi.replace("/", "%2F")
    out = subprocess.run(
        ["curl", "-sL", "-m", str(timeout), "-A", _UA, url], capture_output=True, text=True
    ).stdout
    try:
        return (json.loads(out)["message"].get("title") or [""])[0]
    except Exception:
        return None


def check_doi_titles(
    store: Any,
    ids_by_record: dict[int, list[tuple[str, str, float, str]]],
    *,
    sample: int = 0,
    sleep: float = 0.4,
) -> tuple[list[Finding], int, int, int]:
    """Compare DOI titles against the records that hold them.

    Returns ``(findings, checked, unreachable, cross_language)``.  ``sample=0`` checks every DOI;
    ``cross_language`` counts pairs a character-level ratio cannot judge (one side CJK, the other
    not) — they are excluded rather than scored (see the module docstring).  ``sample`` caps the
    number of *scored* pairs, so a sampled run reports the same exclusions as a full one.
    """
    findings: list[Finding] = []
    checked = unreachable = cross_language = 0
    with store._lock, store._conn() as conn:  # noqa: SLF001 — invariants are store-internal
        titles = {sf_id: title or "" for sf_id, title in conn.execute("SELECT sf_id, title FROM papers")}
    for sf_id, identifiers in ids_by_record.items():
        doi = next((v for t, v, *_ in identifiers if t == "doi"), "")
        if not doi:
            continue
        if sample and checked >= sample:
            break
        crossref = _crossref_title(doi)
        if crossref is None:
            unreachable += 1
            continue
        record_title = titles.get(sf_id, "")
        if is_cross_language(record_title, crossref):
            cross_language += 1
            continue
        checked += 1
        ratio = difflib.SequenceMatcher(None, _norm(record_title), _norm(crossref)).ratio()
        if ratio < MATCH_THRESHOLD:
            findings.append(
                Finding(
                    "doi.title_mismatch",
                    "error",
                    str(sf_id),
                    f"doi {doi} resolves to a different paper (similarity {ratio:.2f}) — triage, not a verdict",
                    {"record": record_title[:80], "crossref": crossref[:80], "similarity": round(ratio, 3)},
                )
            )
        time.sleep(sleep)
    return findings, checked, unreachable, cross_language


def iter_dois(ids_by_record: Iterable[tuple[int, list[tuple[str, ...]]]]) -> list[tuple[int, str]]:
    """Small helper for callers that only want the ``(sf_id, doi)`` pairs."""
    out = []
    for sf_id, identifiers in ids_by_record:
        for row in identifiers:
            if row and row[0] == "doi" and len(row) > 1:
                out.append((sf_id, row[1]))
    return out
