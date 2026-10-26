#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# invariants.py
"""Store invariants — the checks that decide whether a stored fact can be trusted.

Why this module exists (evidence, 2026-09-19 data-integrity pass — `docs/AUDIT_CRITIQUE.md`):
a release could pass every existing gate while the artifact contained 25 DOIs that belong to other
papers, 14 `year` values that were arXiv id prefixes, 18 duplicate records for the same paper and 21
records with no identifier at all.  The tests were green because they ran against fixtures; nothing
ever looked at the production store.

These checks are deterministic, offline by default, and cheap enough to run on every release and in
CI against a copy of the real store.  A network check (DOI → Crossref title) exists but is opt-in
and sampled, because it is the only expensive one and the only one that can fail for reasons that
are not the store's fault.

Severities:
    ``error``   — the store is wrong in a way that produces incorrect answers. Fails ``--strict``.
    ``warning`` — suspicious; may be legitimate but needs a reason on the record.
    ``info``    — a count worth publishing (coverage, e.g. how many records have a year at all).
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = [
    "LOW_CONFIDENCE_THRESHOLD",
    "IDENTIFIER_TYPES",
    "NONPAPER_DOI_SHAPES",
    "DUPLICATE_VERDICTS",
    "DuplicateMember",
    "Finding",
    "InvariantReport",
    "classify_duplicate_pair",
    "plan_duplicate_group",
    "identity_key",
    "normalise_title",
    "strip_inline_markup",
    "is_cross_language",
    "check_store",
    "baseline_diff",
    "ACCEPTED_UNVERIFIED_TAG",
]

#: Identifiers attached automatically below this confidence are treated as unverified: every DOI in
#: this band was wrong when the live store was audited (13/13), so the band is a finding, not noise.
LOW_CONFIDENCE_THRESHOLD = 0.6

#: A record may carry an identifier below that threshold deliberately — then it must say so.
ACCEPTED_UNVERIFIED_TAG = "accepted-unverified"

#: Identifier kinds the store understands. Anything else is a typo that silently hides evidence.
IDENTIFIER_TYPES = frozenset(
    {"arxiv", "doi", "url", "tag", "meta", "authors", "openreview", "issn", "isbn", "pmid", "pmcid",
     "pns", "pdf", "code", "venue", "journal", "semanticscholar"}
)

#: DOI shapes that never point at a paper body. Observed in the live store: a supplementary file
#: (`…/mm1`), a peer-review report (`…/v1/review2`), a correction notice, an R package, an OSTI
#: technical report attached to an unrelated arXiv paper.
NONPAPER_DOI_SHAPES: tuple[tuple[str, str], ...] = (
    ("/mm", "supplementary-material"),
    ("/review", "peer-review-report"),
    ("correction", "correction-notice"),
    ("cran.package", "software-package"),
    ("/rs.", "preprint-server-doi"),
    ("10.2172/", "tech-report-doi"),
)

_YEAR_MIN, _YEAR_MAX = 1900, 2100
_ARXIV_ID = re.compile(r"^\d{4}\.\d{4,5}$")
_DOI_AS_TITLE = re.compile(r"^10\.\d{4,9}/\S+$")
_CITATION_TITLE = re.compile(r"^[A-Z][A-Za-zÀ-ÿ'\-]+,\s+[A-Z]\.|^\s*\S+\s+et al\.", re.UNICODE)


@dataclass
class Finding:
    """One violation, with the evidence needed to judge it."""

    check: str
    severity: str  # error | warning | info
    subject: str  # what it is about: the sf_id, or a group key
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "subject": self.subject,
            "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass
class InvariantReport:
    """Findings plus the coverage numbers that say how much of the store they describe."""

    findings: list[Finding] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    def by_check(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.check] = counts.get(f.check, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": not self.errors,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "by_check": self.by_check(),
            "coverage": self.coverage,
            "findings": [f.as_dict() for f in self.findings],
        }


def normalise_title(title: str, limit: int = 90) -> str:
    """Fold a title to the form used for equality: lowercase, alphanumerics + CJK, truncated."""
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (title or "").lower())[:limit]


#: Inline markup and entities occur in *real* titles: Crossref returns MathML inside the title
#: (`High-<mml:math …>β</mml:math>Equilibria…`), and both the offline audit and the write path
#: compare titles.  A comparison that keeps the markup measures the markup, not the title —
#: `10.1103/PhysRevLett.89.125003` scored 0.165 that way and 0.957 once the tags are dropped
#: (2026-09-25).
_TAG_RE = re.compile(r"<[^>]{0,400}>")
_ENTITY_RE = re.compile(r"&[a-zA-Z]{1,10};|&#\d{1,6};")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def strip_inline_markup(text: str) -> str:
    """Drop inline tags and entities from a title (the single implementation; used by both checks)."""
    text = _TAG_RE.sub(" ", text or "")
    text = _ENTITY_RE.sub(" ", text)
    return html.unescape(text)


def is_cross_language(left: str, right: str) -> bool:
    """True when one title carries CJK and the other does not.

    Such a pair cannot be scored by a character-level ratio — a 《物理学报》 record against the
    English title Crossref holds scores 0.00 — so callers must not treat "low score" as "wrong".
    """
    return bool(_CJK_RE.search(left or "")) != bool(_CJK_RE.search(right or ""))


def identity_key(title: str, year: int, identifiers: Iterable[tuple[str, ...]]) -> str:
    """The key that decides whether two records are the same work: **the title**, not the identifier.

    The obvious design — key on the DOI, else the arXiv id, else the title — does not work here, and
    the test suite proved it on the first run: ``identifiers`` carries ``UNIQUE(id_type, id_value)``,
    so two copies of the same paper *cannot* share an identifier by construction.  Every real
    duplicate pair in the live store was exactly that shape (one copy with the DOI, one with the
    arXiv id), so identifier-first keying finds zero duplicates.  The title is the only field the
    copies have in common; identifiers are evidence *for a merge decision*, not the grouping key.

    `identifiers` is still used as the fallback when a record has no usable title.
    """
    norm = normalise_title(title)
    if norm:
        # Title only: the year is weak evidence and, used in the key, it splits exactly the pairs
        # worth reviewing (one copy with a year, one without). Year disagreement is handled as a
        # severity question by `check_store` and as a merge guard by `store dedup`.
        return f"title:{norm}"
    ids = {t.lower(): v for t, v, *_ in identifiers}
    if ids.get("doi"):
        return "doi:" + ids["doi"].lower()
    if ids.get("arxiv"):
        return "arxiv:" + ids["arxiv"]
    return ""


#: What a record that shares its identity with another one turns out to be.
DUPLICATE_VERDICTS = ("mergeable", "drop_wrong_doi", "version_pair", "human", "not_same_work")


@dataclass(frozen=True)
class DuplicateMember:
    """One record of a duplicate-identity group, plus the evidence needed to rank it.

    ``doi_matches_title`` is ``None`` when nobody looked (the offline path) and ``True``/``False`` when
    a registry answered.  A missing answer must never be read as a bad one.
    """

    sf_id: int
    title: str
    year: int = 0
    kinds: frozenset[str] = frozenset()
    doi_matches_title: bool | None = None


def classify_duplicate_pair(keep: DuplicateMember, drop: DuplicateMember) -> str:
    """What ``drop`` is, given ``keep`` — one of :data:`DUPLICATE_VERDICTS`.

    Offline, the rule stays identifier *kinds*: one copy with the DOI and one with the arXiv id is one
    work filed twice (``mergeable``); overlapping kinds looks like two artefacts of one work — a journal
    paper and its OSTI report — and is left alone (``human``).

    That rule was not enough on 2026-09-25: a pair where *both* copies held a DOI was judged "two
    artefacts", but one of those DOIs described a different paper, so the wrong DOI stayed in the store.
    When a registry has answered, its answer outranks the kinds heuristic:

    * ``drop_wrong_doi`` — ``drop``'s DOI describes another paper while ``keep``'s describes this one.
      Merging would carry the wrong DOI across, so the caller discards it rather than moving it.
    * ``version_pair`` — both DOIs describe this title: journal paper plus report, both kept.
    """

    if normalise_title(keep.title) != normalise_title(drop.title):
        return "not_same_work"
    if drop.doi_matches_title is False and keep.doi_matches_title is True:
        return "drop_wrong_doi"
    if keep.doi_matches_title and drop.doi_matches_title:
        return "version_pair"
    if not (keep.kinds & drop.kinds) and (keep.year == drop.year or not keep.year or not drop.year):
        return "mergeable"
    return "human"


def plan_duplicate_group(
    members: list[DuplicateMember],
) -> tuple[DuplicateMember | None, list[tuple[DuplicateMember, str]]]:
    """Rank a group and judge every member but the first.

    Ranking is evidence-first, not richness-first: a record whose DOI describes its own title beats an
    unverified one, which beats one whose DOI describes a different paper.  That order matters — in the
    live 2026-09-25 pair the copy *holding* a DOI was the wrong copy, so "keep the record with the most
    identifiers" would have kept the mistake and discarded the correct record.  Identifier count and
    then a stable id order break ties, so the plan never depends on dict ordering.
    """

    if not members:
        return None, []
    rank = {True: 2, None: 1, False: 0}
    ordered = sorted(members, key=lambda m: (-rank[m.doi_matches_title], -len(m.kinds), m.sf_id))
    keep, rest = ordered[0], ordered[1:]
    return keep, [(m, classify_duplicate_pair(keep, m)) for m in rest]


def _identifier_rows(store: Any) -> dict[int, list[tuple[str, str, float, str]]]:
    """``{sf_id: [(id_type, id_value, confidence, source)]}`` — one query for the whole store."""
    with store._lock, store._conn() as conn:  # noqa: SLF001 — invariants are store-internal by design
        rows = conn.execute(
            "SELECT sf_id, id_type, id_value, COALESCE(confidence, 1.0), COALESCE(source, '')"
            " FROM identifiers"
        ).fetchall()
    out: dict[int, list[tuple[str, str, float, str]]] = {}
    for sf_id, id_type, id_value, conf, source in rows:
        out.setdefault(sf_id, []).append((id_type, id_value, float(conf), source))
    return out


def check_store(
    store: Any,
    *,
    network: bool = False,
    sample: int = 0,
    only_sf_ids: Iterable[int] | None = None,
) -> InvariantReport:
    """Run every offline invariant, plus the optional sampled DOI check.

    ``network=True`` verifies up to ``sample`` DOIs against Crossref (0 = all).  Only the sampled
    check can fail for external reasons, which is why it is off by default: the offline set is the
    release gate, the sampled set is a periodic audit.

    ``only_sf_ids`` narrows the *findings* to the records a caller just wrote, so a batch import can
    check its own output at the end of the run (``pipelines.StorePipeline``) instead of waiting for
    the next full audit.  Coverage still describes the whole store — the point is to see the defect
    the moment it is created, not to hide what else is there.
    """
    report = InvariantReport()
    ids_by_record = _identifier_rows(store)
    with store._lock, store._conn() as conn:  # noqa: SLF001
        papers = conn.execute(
            "SELECT sf_id, title, COALESCE(year, 0), COALESCE(venue, ''), COALESCE(item_type, ''),"
            " COALESCE(item_type_src, '') FROM papers"
        ).fetchall()

    seen_keys: dict[str, list[int]] = {}
    with_ids = 0
    with_year = 0
    for sf_id, title, year, venue, item_type, _item_type_src in papers:
        title = title or ""
        identifiers = ids_by_record.get(sf_id, [])
        tags = {v.strip().lower() for t, v, *_ in identifiers if t == "tag"}

        # 1. year domain — `year=0` means unset; anything else outside the domain is a parse error
        #    (the live store held 14 values taken from arXiv id prefixes: 2206.14588 → year 2206).
        if year and not (_YEAR_MIN <= year <= _YEAR_MAX):
            report.findings.append(
                Finding(
                    "year.out_of_domain",
                    "error",
                    str(sf_id),
                    f"year={year} is outside [{_YEAR_MIN}, {_YEAR_MAX}] and is not 0 (unset)",
                    {"title": title[:80], "year": year, "arxiv": next((row[1] for row in identifiers if row[0] == "arxiv"), "")},
                )
            )
        if year:
            with_year += 1

        # 2. evidence presence — a record nobody can look up cannot be verified later.
        if identifiers:
            with_ids += 1
        elif ACCEPTED_UNVERIFIED_TAG not in tags:
            report.findings.append(
                Finding(
                    "record.no_identifier",
                    "warning",
                    str(sf_id),
                    "record has no identifier at all (attach one, or tag it "
                    f"'{ACCEPTED_UNVERIFIED_TAG}' to record that this is intentional)",
                    {"title": title[:80], "venue": venue[:40]},
                )
            )

        # 3. title hygiene — a title equal to its own identifier, or a citation string, is not a
        #    title: it silently answers every downstream question ("what is this paper?") wrongly.
        if title.strip():
            identical = False
            for t, v, *_ in identifiers:
                if title.strip() == v.strip():
                    report.findings.append(
                        Finding(
                            "title.is_identifier",
                            "error",
                            str(sf_id),
                            f"title equals its own {t} identifier ({v})",
                            {"title": title[:80]},
                        )
                    )
                    identical = True
                    break
            if identical:
                pass
            elif _DOI_AS_TITLE.match(title.strip()):
                report.findings.append(
                    Finding("title.is_identifier", "error", str(sf_id), "title is a bare DOI string",
                            {"title": title[:80]})
                )
            elif _CITATION_TITLE.match(title.strip()):
                report.findings.append(
                    Finding(
                        "title.is_citation",
                        "warning",
                        str(sf_id),
                        "title looks like a reference entry (author list first), not a paper title",
                        {"title": title[:90]},
                    )
                )
        else:
            report.findings.append(
                Finding("title.empty", "error", str(sf_id), "record has no title", {"venue": venue[:40]})
            )

        # 4. identifier vocabulary + confidence band
        for t, v, conf, source in identifiers:
            if t.lower() not in IDENTIFIER_TYPES:
                report.findings.append(
                    Finding("identifier.unknown_type", "error", str(sf_id), f"id_type={t!r} is not a known kind",
                            {"id_value": v[:60]})
                )
            if t == "doi" and conf < LOW_CONFIDENCE_THRESHOLD and ACCEPTED_UNVERIFIED_TAG not in tags:
                report.findings.append(
                    Finding(
                        "identifier.low_confidence",
                        "warning",
                        str(sf_id),
                        f"doi {v} attached at confidence {conf:.2f} (< {LOW_CONFIDENCE_THRESHOLD}) — "
                        f"every DOI in this band was wrong when the live store was audited",
                        {"confidence": round(conf, 3), "source": source, "title": title[:70]},
                    )
                )
            if t == "doi":
                low = v.lower()
                for shape, kind in NONPAPER_DOI_SHAPES:
                    if shape in low:
                        report.findings.append(
                            Finding("doi.non_paper_shape", "warning", str(sf_id),
                                    f"doi {v} has a {kind} shape — it probably does not identify the paper body",
                                    {"shape": shape, "kind": kind})
                        )
                        break

        # 5. item_type vocabulary
        if item_type:
            from hfpapers.item_types import ITEM_TYPES

            if item_type not in ITEM_TYPES:
                report.findings.append(
                    Finding("item_type.unknown", "error", str(sf_id), f"item_type={item_type!r} is not in the vocabulary", {})
                )

    # 6. duplicate identity — one work, one record. Checked last so the findings above are already
    #    attributed to the record that carries them.
    for sf_id, title, year, _venue, _it, _src in papers:
        key = identity_key(title, year, [(row[0], row[1]) for row in ids_by_record.get(sf_id, [])])
        if key:
            seen_keys.setdefault(key, []).append(sf_id)
    years = {sf_id: year for sf_id, _t, year, _v, _i, _s in papers}
    for key, members in seen_keys.items():
        if len(members) > 1:
            known = {years.get(sf_id, 0) for sf_id in members if years.get(sf_id, 0)}
            conflicting = len(known) > 1
            for sf_id in members:
                report.findings.append(
                    Finding(
                        "record.duplicate_identity" if not conflicting else "record.title_collision",
                        "warning" if conflicting else "error",
                        str(sf_id),
                        (
                            f"{len(members)} records share the title but disagree on the year "
                            f"{sorted(known)} — different works, or one of them has a bad year"
                            if conflicting
                            else f"{len(members)} records share identity {key}"
                        ),
                        {"group": members, "years": sorted(known)},
                    )
                )

    # 7. optional sampled network check (the only expensive one)
    if network:
        from hfpapers.invariants_network import (  # local import: keeps core offline
            check_doi_titles,
            refine_duplicate_findings,
        )

        findings, checked, failed, cross_language = check_doi_titles(store, ids_by_record, sample=sample)
        report.findings.extend(findings)
        # Duplicate groups get a second look here: whether two records sharing a title are a defect
        # depends on what their own DOIs say, which only a registry can settle (v0.19.12).
        groups, dois_checked = refine_duplicate_findings(report, store)
        report.coverage["duplicate_groups_judged"] = groups
        report.coverage["duplicate_dois_checked"] = dois_checked
        report.coverage["doi_title_checked"] = checked
        report.coverage["doi_title_unreachable"] = failed
        # Pairs a character-level ratio cannot judge (one side CJK) — excluded, not scored.
        report.coverage["doi_title_cross_language"] = cross_language

    report.coverage.update(
        {
            "papers": len(papers),
            "with_identifier": with_ids,
            "with_year": with_year,
            "year_coverage": round(with_year / len(papers), 3) if papers else 0.0,
            "identities": len(seen_keys),
        }
    )

    if only_sf_ids is not None:
        wanted = {str(int(sf)) for sf in only_sf_ids}
        report.findings = [f for f in report.findings if f.subject in wanted]
    return report


def format_report(report: InvariantReport, *, limit: int = 20) -> str:
    """Human-readable summary — counts first, then the most consequential findings."""
    lines = [
        f"invariants: {len(report.errors)} error(s), {len(report.warnings)} warning(s)"
        f" over {report.coverage.get('papers', 0)} record(s)"
    ]
    for check, count in report.by_check().items():
        lines.append(f"  {check}: {count}")
    if report.coverage:
        cov = ", ".join(f"{k}={v}" for k, v in report.coverage.items())
        lines.append(f"  coverage: {cov}")
    shown = [f for f in report.findings if f.severity == "error"] + report.warnings
    for f in shown[:limit]:
        lines.append(f"  [{f.severity}] {f.check} · {f.subject} · {f.detail}")
    if len(shown) > limit:
        lines.append(f"  … {len(shown) - limit} more (use --json for the full list)")
    return "\n".join(lines)


def report_json(report: InvariantReport) -> str:
    return json.dumps(report.as_dict(), ensure_ascii=False, indent=1)


def baseline_diff(report: "InvariantReport", baseline: dict[str, int]) -> tuple[list[str], list[str]]:
    """Compare per-check counts against a recorded baseline.

    Returns ``(regressions, improvements)``.  A gate that is red on the day it lands gets ignored —
    and one that is green because it hides findings is worse — so the rule is a **ratchet**: the
    baseline may only shrink, and any check that grew is a regression the release must justify.
    """
    current = report.by_check()
    regressions = [f"{k}: {baseline.get(k, 0)} → {v}" for k, v in current.items() if v > baseline.get(k, 0)]
    improvements = [f"{k}: {baseline.get(k, 0)} → {v}" for k, v in current.items() if v < baseline.get(k, 0)]
    improvements += [f"{k}: {baseline[k]} → 0" for k in baseline if k not in current and baseline[k]]
    return regressions, improvements
