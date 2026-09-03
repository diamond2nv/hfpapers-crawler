#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""contracts.py — Pydantic contract models at API/JSON boundaries only.

Discipline (AGENTS.md + project convention): pydantic lives at CONTRACT
boundaries (external API payloads, cross-machine JSON), never inside the
0-token mechanical layer (paper_store rows, audit JSONL — those stay plain
dicts with defensive reads).

Current contracts:
- ZoteroItem: sync-back item from the Zotero LOCAL API (or pyzotero). Encodes
  the scholarly-item filter discipline (roadmap §2b): only DOI/arXiv-bearing
  academic items are useful to hfpapers-crawler; web pages, books, reports
  and other non-scholarly items must never enter papers.db.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

# Zotero item types that are directly scholarly (fast path). Items NOT in this
# set are still accepted when they carry a DOI/arXiv id (preprint-shaped items
# often surface as journalArticle with archiveID=arXiv — type field unreliable).
SCHOLARLY_ITEM_TYPES = frozenset(
    {"journalArticle", "conferencePaper", "preprint", "workingPaper"}
)

_DOI_RE = re.compile(r"^10\.\d{4,9}/[^\s]+$")
_ARXIV_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$", re.IGNORECASE)


class ZoteroItem(BaseModel):
    """One item returned by the Zotero local API (or pyzotero mapping).

    Fields follow the Zotero item JSON surface; unknown fields are tolerated.
    The scholarly filter lives here as a single source of truth so sync-back,
    CLI and future MCP tooling all apply the same discipline.
    """

    key: str = Field(..., description="Zotero item key")
    item_type: str = Field("", alias="itemType")
    title: str = ""
    doi: str = Field("", alias="DOI")
    arxiv_id: str = Field("", alias="arxivID")
    archive_id: str = Field("", alias="archiveID")
    extra: str = ""  # Zotero Extra field (free text, may hold arXiv/DOI notes)
    collection_keys: list[str] = Field(default_factory=list, alias="collections")

    model_config = {"populate_by_name": True}

    @field_validator("doi", mode="before")
    @classmethod
    def _norm_doi(cls, v: Any) -> str:
        if v is None:
            return ""
        s = str(v).strip()
        return s[4:] if s.lower().startswith("doi:") else s

    @staticmethod
    def _clean_arxiv(raw: str) -> str:
        """Normalize an arXiv id value (strip arXiv: prefix, lowercase)."""
        s = str(raw or "").strip()
        s = re.sub(r"^arxiv\s*:\s*", "", s, flags=re.IGNORECASE).strip()
        return s

    @property
    def scholarly(self) -> bool:
        """Scholarly ⇔ carries a DOI or an arXiv ID (identifier judgment).

        itemType whitelist is a fast path only — the identifier is the
        authority (Zotero type fields are unreliable for preprint-shaped
        items). Roadmap §2b: 期刊/preprint 皆可；无 ID 的网页/书籍/报告丢弃.
        """
        if self.doi and _DOI_RE.match(self.doi):
            return True
        candidate = self._clean_arxiv(self.arxiv_id or self.archive_id)
        return bool(candidate and _ARXIV_RE.match(candidate))

    @property
    def paper_identifier(self) -> tuple[str, str] | None:
        """Preferred lookup identifier for paper_store matching.

        Returns ("arxiv", id) when an arXiv id exists, else ("doi", doi).
        """
        arxiv = self._clean_arxiv(self.arxiv_id or self.archive_id)
        if arxiv and _ARXIV_RE.match(arxiv):
            return ("arxiv", arxiv.lower())
        if self.doi and _DOI_RE.match(self.doi):
            return ("doi", self.doi.lower())
        return None

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        # Keep serialization friendly for JSONL/CLI by naming output fields.
        kwargs.setdefault("by_alias", True)
        return super().model_dump(*args, **kwargs)
