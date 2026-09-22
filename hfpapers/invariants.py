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

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = [
    "LOW_CONFIDENCE_THRESHOLD",
    "IDENTIFIER_TYPES",
    "NONPAPER_DOI_SHAPES",
    "Finding",
    "InvariantReport",
    "identity_key",
    "normalise_title",
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


def check_store(store: Any, *, network: bool = False, sample: int = 0) -> InvariantReport:
    """Run every offline invariant, plus the optional sampled DOI check.

    ``network=True`` verifies up to ``sample`` DOIs against Crossref (0 = all).  Only the sampled
    check can fail for external reasons, which is why it is off by default: the offline set is the
    release gate, the sampled set is a periodic audit.
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
        from hfpapers.invariants_network import check_doi_titles  # local import: keeps core offline

        findings, checked, failed = check_doi_titles(store, ids_by_record, sample=sample)
        report.findings.extend(findings)
        report.coverage["doi_title_checked"] = checked
        report.coverage["doi_title_unreachable"] = failed

    report.coverage.update(
        {
            "papers": len(papers),
            "with_identifier": with_ids,
            "with_year": with_year,
            "year_coverage": round(with_year / len(papers), 3) if papers else 0.0,
            "identities": len(seen_keys),
        }
    )
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
