#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bib.py — BibTeX citation metadata verification.

Parses references.bib, cross-checks against arXiv API and DOI.org.
Ported from coc.references.verify (Hermes Agent).
"""

import json
import logging
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from hfpclawer.audit.similarity import normalize_title

logger = logging.getLogger("hfpclawer.audit.bib")


@dataclass
class BibEntry:
    """A single BibTeX entry with parsed fields."""
    cite_key: str = ""
    entry_type: str = "article"
    title: str = ""
    title_norm: str = ""
    authors: list[str] = field(default_factory=list)
    year: int = 0
    arxiv_id: str = ""
    doi: str = ""
    journal: str = ""
    url: str = ""


@dataclass
class BibVerification:
    """Result of verifying a BibTeX entry against its source."""
    cite_key: str
    source: str  # arxiv | doi | isbn | none
    matched: list[str] = field(default_factory=list)
    mismatched: list[str] = field(default_factory=list)
    error: str = ""
    success: bool = False
    elapsed_s: float = 0.0
    fetched: dict[str, Any] = field(default_factory=dict)


def parse_bib(path: Path) -> list[BibEntry]:
    """Parse a references.bib file into structured entries."""
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8", errors="ignore")
    entries: list[BibEntry] = []

    pattern = re.compile(r'@(\w+)\{(\w+),\s*((?:.|\n)*?)\n\}', re.MULTILINE)
    for match in pattern.finditer(text):
        etype = match.group(1)
        key = match.group(2)
        body = match.group(3)

        entry = BibEntry(cite_key=key, entry_type=etype)
        entry.title = _extract_bib_field(body, "title")
        entry.title_norm = normalize_title(entry.title) if entry.title else ""
        entry.year = int(_extract_bib_field(body, "year") or 0)
        entry.journal = _extract_bib_field(body, "journal")
        entry.url = _extract_bib_field(body, "url")

        authors_raw = _extract_bib_field(body, "author")
        if authors_raw:
            entry.authors = [a.strip() for a in authors_raw.replace("\n", " ").split(" and ")]

        doi = _extract_bib_field(body, "doi")
        if doi:
            entry.doi = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', doi.strip().lower())
        eprint = _extract_bib_field(body, "eprint")
        if eprint:
            entry.arxiv_id = _normalise_arxiv_id(eprint)
        if not entry.arxiv_id:
            note = _extract_bib_field(body, "note")
            if note:
                m = re.search(r'arXiv[:.\s]*([\d.]+)', note)
                if m:
                    entry.arxiv_id = m.group(1)

        entries.append(entry)

    return entries


def verify_bib_entry(entry: BibEntry, timeout: float = 15.0) -> BibVerification:
    """Cross-check a BibEntry against its authoritative source.

    Priority: arxiv_id > doi.
    Returns BibVerification with matched/mismatched fields.
    """
    start = time.time()

    if entry.arxiv_id:
        result = _verify_via_arxiv(entry, timeout=timeout)
    elif entry.doi:
        result = _verify_via_doi(entry, timeout=timeout)
    else:
        result = BibVerification(
            cite_key=entry.cite_key,
            source="none",
            error="No arxiv_id or doi — cannot auto-verify",
        )

    result.elapsed_s = time.time() - start
    result.success = len(result.mismatched) == 0 and result.error == "" and len(result.matched) > 0
    return result


# ── arXiv API ──────────────────────────────────────────────


def _normalise_arxiv_id(raw: str) -> str:
    s = raw.strip().lower()
    s = re.sub(r"^arxiv:", "", s)
    s = re.sub(r"v\d+$", "", s)
    return s


def _verify_via_arxiv(entry: BibEntry, timeout: float = 15.0) -> BibVerification:
    result = BibVerification(cite_key=entry.cite_key, source="arxiv")
    arxiv_id = _normalise_arxiv_id(entry.arxiv_id)
    url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}&max_results=1"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hfpclawer-audit/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            xml_data = resp.read().decode("utf-8")
    except Exception as exc:
        result.error = f"arXiv API error: {exc}"
        return result

    root = ET.fromstring(xml_data)
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    entries_xml = root.findall("atom:entry", ns)
    if not entries_xml:
        result.error = "No entry found on arXiv"
        return result

    entry_xml = entries_xml[0]
    title_raw = entry_xml.findtext("atom:title", "", ns).strip().replace("\n", " ").replace("  ", " ")
    result.fetched["title"] = title_raw

    entry_norm = normalize_title(entry.title)
    arxiv_norm = normalize_title(title_raw)
    if entry_norm == arxiv_norm:
        result.matched.append("title")
    elif entry_norm in arxiv_norm or arxiv_norm in entry_norm:
        result.matched.append("title (partial)")
        result.mismatched.append(f"title (arXiv: '{title_raw[:80]}...')")
    else:
        result.mismatched.append(f"title (arXiv: '{title_raw[:80]}...')")

    authors_xml = entry_xml.findall("atom:author/atom:name", ns)
    arxiv_authors = [a.text.strip() for a in authors_xml if a.text]
    result.fetched["authors"] = arxiv_authors
    if arxiv_authors and entry.authors:
        first_arxiv = arxiv_authors[0].split(",")[0].strip().lower()
        first_entry = entry.authors[0].split(",")[0].strip().lower()
        if first_arxiv == first_entry:
            result.matched.append("authors (first)")
        else:
            result.mismatched.append(f"authors (arXiv first: '{arxiv_authors[0]}')")

    published = entry_xml.findtext("atom:published", "", ns)
    if published and entry.year:
        arxiv_year = published[:4]
        if str(entry.year) == arxiv_year:
            result.matched.append("year")
        else:
            result.mismatched.append(f"year (arXiv: {arxiv_year})")
        result.fetched["year"] = int(arxiv_year)

    arxiv_doi = ""
    for link in entry_xml.findall("atom:link", ns):
        if link.get("title") == "doi":
            arxiv_doi = link.get("href", "").replace("https://doi.org/", "")
            result.fetched["doi"] = arxiv_doi
    if entry.doi and arxiv_doi:
        if entry.doi == arxiv_doi:
            result.matched.append("doi")

    return result


# ── DOI verification ───────────────────────────────────────


def _verify_via_doi(entry: BibEntry, timeout: float = 15.0) -> BibVerification:
    result = BibVerification(cite_key=entry.cite_key, source="doi")
    doi = entry.doi
    if not re.match(r"^10\.\d{4,}/", doi):
        result.error = f"Invalid DOI: {doi}"
        return result

    url = f"https://doi.org/{doi}"
    try:
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.citationstyles.csl+json",
            "User-Agent": "hfpclawer-audit/1.0",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        result.error = f"DOI API error: {exc}"
        return result

    if "title" in data:
        doi_title = data["title"].strip()
        if normalize_title(entry.title) == normalize_title(doi_title):
            result.matched.append("title")
        else:
            result.mismatched.append(f"title (DOI: '{doi_title[:80]}')")
        result.fetched["title"] = doi_title

    if "author" in data:
        doi_authors = [f"{a.get('family', '')}, {a.get('given', '')}" for a in data["author"]]
        result.fetched["authors"] = doi_authors
        if doi_authors and entry.authors:
            first_doi = doi_authors[0].split(",")[0].strip().lower()
            first_entry = entry.authors[0].split(",")[0].strip().lower()
            if first_doi == first_entry:
                result.matched.append("authors (first)")
            else:
                result.mismatched.append(f"authors (DOI first: '{doi_authors[0]}')")

    for key in ("published-print", "published-online", "issued"):
        if key in data and "date-parts" in data[key]:
            doi_year = str(data[key]["date-parts"][0][0])
            if str(entry.year) == doi_year:
                result.matched.append("year")
            else:
                result.mismatched.append(f"year (DOI: {doi_year})")
            result.fetched["year"] = int(doi_year)
            break

    return result


# ── Helpers ────────────────────────────────────────────────


def _extract_bib_field(body: str, field: str) -> str:
    for delim in [("{", "}"), ('"', '"')]:
        m = re.search(
            r'^\s*' + field + r'\s*=\s*' + re.escape(delim[0])
            + r'([^' + re.escape(delim[1]) + r']*)' + re.escape(delim[1]),
            body, re.MULTILINE | re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()
    return ""
