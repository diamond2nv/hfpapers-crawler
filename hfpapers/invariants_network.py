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
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import time
from typing import Any, Iterable

from hfpapers.invariants import Finding

MATCH_THRESHOLD = 0.62
_CROSSREF = "https://api.crossref.org/works/"
_UA = "hfpclawer (mailto:dev@example.com)"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (text or "").lower())[:80]


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
) -> tuple[list[Finding], int, int]:
    """Compare DOI titles against the records that hold them.

    Returns ``(findings, checked, unreachable)``.  ``sample=0`` checks every DOI.
    """
    findings: list[Finding] = []
    checked = unreachable = 0
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
        checked += 1
        record_title = titles.get(sf_id, "")
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
    return findings, checked, unreachable


def iter_dois(ids_by_record: Iterable[tuple[int, list[tuple[str, ...]]]]) -> list[tuple[int, str]]:
    """Small helper for callers that only want the ``(sf_id, doi)`` pairs."""
    out = []
    for sf_id, identifiers in ids_by_record:
        for row in identifiers:
            if row and row[0] == "doi" and len(row) > 1:
                out.append((sf_id, row[1]))
    return out
