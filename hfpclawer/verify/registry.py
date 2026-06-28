#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
registry.py — FormulaRegistry for hfpclawer.

JSONL-backed formula database with schema versioning, lineage tracking,
and expiry-aware status management.

Schema:
    registry_schema_version: int       # Current version (incremented on schema change)
    fid: str                           # Unique formula ID (e.g. "eq:biot-savart-segment")
    latex: str                         # LaTeX representation (canonical form)
    sympy: str                         # SymPy expression string (optional)
    source_keys: list[str]             # Reference keys (e.g. ["Griffiths2023"])
    extracted_from: str | None         # Paper sf_id from which this was extracted
    equation_index: int | None         # Equation number within the source paper
    pint_dimension: str                # Physical dimension string (e.g. "magnetic flux density")
    verification_status: str           # "unverified" | "verified" | "expired" | "failed"
    verified_at: str | None            # ISO timestamp of last verification
    expires_at: str | None             # ISO timestamp after which status reverts to "expired"
    verifications: list[dict]          # List of {layer, passed, timestamp, detail}
    tags: list[str]                    # Category tags (e.g. ["magnetostatics", "biot-savart"])
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("hfpclawer.verify.registry")

# ─── Schema version ──────────────────────────
CURRENT_SCHEMA_VERSION = 1
DEFAULT_EXPIRY_DAYS = 365  # Re-verify after 1 year


# ════════════════════════════════════════════
# FormulaEntry data class
# ════════════════════════════════════════════


class FormulaEntry:
    """Single formula entry with schema-versioned fields."""

    __slots__ = (
        "registry_schema_version",
        "fid",
        "latex",
        "sympy",
        "source_keys",
        "extracted_from",
        "equation_index",
        "pint_dimension",
        "verification_status",
        "verified_at",
        "expires_at",
        "verifications",
        "tags",
    )

    def __init__(
        self,
        fid: str,
        latex: str,
        sympy: str = "",
        source_keys: Optional[list[str]] = None,
        extracted_from: Optional[str] = None,
        equation_index: Optional[int] = None,
        pint_dimension: str = "",
        verification_status: str = "unverified",
        verified_at: Optional[str] = None,
        expires_at: Optional[str] = None,
        verifications: Optional[list[dict]] = None,
        tags: Optional[list[str]] = None,
        registry_schema_version: int = CURRENT_SCHEMA_VERSION,
    ):
        self.registry_schema_version = registry_schema_version
        self.fid = fid
        self.latex = latex
        self.sympy = sympy
        self.source_keys = source_keys or []
        self.extracted_from = extracted_from
        self.equation_index = equation_index
        self.pint_dimension = pint_dimension
        self.verification_status = verification_status
        self.verified_at = verified_at
        self.expires_at = expires_at
        self.verifications = verifications or []
        self.tags = tags or []

    @classmethod
    def from_dict(cls, data: dict) -> "FormulaEntry":
        """Create from dict (with schema validation)."""
        schema_v = data.get("registry_schema_version", 0)
        if schema_v > CURRENT_SCHEMA_VERSION:
            logger.warning(
                "FormulaEntry schema_version=%d > CURRENT(%d); "
                "may have unknown fields",
                schema_v, CURRENT_SCHEMA_VERSION,
            )
        # Filter to known slots only
        known = {k: data[k] for k in cls.__slots__ if k in data}
        return cls(**known)

    def to_dict(self) -> dict:
        """Serialize to dict for JSONL export."""
        return {k: getattr(self, k) for k in self.__slots__}

    @property
    def is_expired(self) -> bool:
        """Check if the entry has expired and needs re-verification."""
        if not self.expires_at:
            return False
        try:
            expires = datetime.fromisoformat(self.expires_at)
            return datetime.now(timezone.utc) > expires
        except (ValueError, TypeError):
            return False

    @property
    def is_verified(self) -> bool:
        """True if verified AND not expired."""
        return (
            self.verification_status == "verified"
            and not self.is_expired
        )

    def mark_verified(self, layer: str, detail: str = "", ttl_days: int = DEFAULT_EXPIRY_DAYS):
        """Mark a verification layer as passed."""
        now = datetime.now(timezone.utc)
        self.verifications.append({
            "layer": layer,
            "passed": True,
            "timestamp": now.isoformat(),
            "detail": detail,
        })
        self.verification_status = "verified"
        self.verified_at = now.isoformat()
        self.expires_at = (now + timedelta(days=ttl_days)).isoformat()

    def mark_failed(self, layer: str, detail: str = ""):
        """Mark a verification layer as failed."""
        self.verifications.append({
            "layer": layer,
            "passed": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "detail": detail,
        })
        self.verification_status = "failed"

    def __repr__(self) -> str:
        return (
            f"FormulaEntry(fid={self.fid!r}, "
            f"status={self.verification_status!r}, "
            f"v{self.registry_schema_version})"
        )


# ════════════════════════════════════════════
# FormulaRegistry — JSONL-backed database
# ════════════════════════════════════════════


class FormulaRegistry:
    """JSONL-backed formula registry with lazy loading.

    Performance guide:
      < 1K entries: full JSONL in memory (fast)
      1K-10K entries: JSONL + index (acceptable)
      > 10K entries: consider SQLite backend
    """

    def __init__(self, path: str | Path = "formula_registry.jsonl"):
        self.path = Path(path)
        self._entries: Optional[list[FormulaEntry]] = None
        self._index: dict[str, int] = {}  # fid → index

    # ── Load / save ────────────────────────

    def load_all(self) -> list[FormulaEntry]:
        """Lazy-load all entries from JSONL."""
        if self._entries is not None:
            return self._entries
        if not self.path.exists():
            self._entries = []
            self._index = {}
            return self._entries

        entries: list[FormulaEntry] = []
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = FormulaEntry.from_dict(data)
                    entries.append(entry)
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    logger.warning("Skipping invalid registry line: %s", exc)

        self._entries = entries
        self._index = {e.fid: i for i, e in enumerate(entries)}
        logger.info(
            "Loaded %d formula entries from %s (schema v%d)",
            len(entries), self.path, CURRENT_SCHEMA_VERSION,
        )
        return entries

    def save(self):
        """Write all entries back to JSONL."""
        entries = self._entries
        if entries is None:
            entries = self.load_all()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        logger.info("Saved %d entries to %s", len(entries), self.path)

    # ── CRUD ───────────────────────────────

    def add(self, entry: FormulaEntry) -> bool:
        """Add a new entry. Returns False if fid already exists."""
        entries = self.load_all()  # Ensure loaded

        # Schema version check
        if entry.registry_schema_version != CURRENT_SCHEMA_VERSION:
            logger.warning(
                "Adding entry with schema v%d (current v%d); "
                "auto-upgrading",
                entry.registry_schema_version, CURRENT_SCHEMA_VERSION,
            )
            entry.registry_schema_version = CURRENT_SCHEMA_VERSION

        if entry.fid in self._index:
            logger.warning("Duplicate fid: %s (skipped)", entry.fid)
            return False

        entries.append(entry)
        self._index[entry.fid] = len(entries) - 1
        return True

    def get(self, fid: str) -> Optional[FormulaEntry]:
        """Get entry by fid."""
        self.load_all()
        idx = self._index.get(fid)
        if idx is None:
            return None
        return self._entries[idx]

    def update(self, fid: str, **kwargs) -> bool:
        """Update fields of an existing entry in memory.
        Call save() to persist changes to disk.
        """
        entry = self.get(fid)
        if entry is None:
            return False
        for key, value in kwargs.items():
            if hasattr(entry, key):
                setattr(entry, key, value)
            else:
                logger.warning("Unknown field: %s (skipped)", key)
        return True

    def remove(self, fid: str) -> bool:
        """Remove entry by fid. Rebuilds index after removal."""
        entries = self.load_all()
        if fid not in self._index:
            return False
        idx = self._index[fid]
        entries.pop(idx)
        # Rebuild index
        self._index = {e.fid: i for i, e in enumerate(entries)}
        return True

    # ── Query ──────────────────────────────

    def get_by_status(self, status: str) -> list[FormulaEntry]:
        """Filter by verification status."""
        return [e for e in self.load_all() if e.verification_status == status]

    def get_by_tag(self, tag: str) -> list[FormulaEntry]:
        """Filter by tag."""
        return [e for e in self.load_all() if tag in e.tags]

    def get_by_source(self, source_sf_id: str) -> list[FormulaEntry]:
        """Get all formulas extracted from a specific paper."""
        return [
            e for e in self.load_all()
            if e.extracted_from == source_sf_id
        ]

    def get_unverified(self) -> list[FormulaEntry]:
        """Get all unverified or expired entries."""
        results = []
        for e in self.load_all():
            if e.verification_status == "unverified":
                results.append(e)
            elif e.verification_status == "verified" and e.is_expired:
                results.append(e)
        return results

    def get_expired(self) -> list[FormulaEntry]:
        """Get entries whose TTL has expired."""
        return [e for e in self.load_all() if e.is_expired]

    def count(self) -> int:
        """Total number of entries."""
        return len(self.load_all())

    def stats(self) -> dict[str, Any]:
        """Registry statistics."""
        entries = self.load_all()
        statuses: dict[str, int] = {}
        for e in entries:
            statuses[e.verification_status] = statuses.get(e.verification_status, 0) + 1
        return {
            "total": len(entries),
            "by_status": statuses,
            "expired": len(self.get_expired()),
            "schema_version": CURRENT_SCHEMA_VERSION,
            "path": str(self.path),
        }
