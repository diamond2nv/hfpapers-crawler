#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for FormulaRegistry (verify/registry.py)."""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hfpclawer.verify.registry import (
    CURRENT_SCHEMA_VERSION,
    FormulaEntry,
    FormulaRegistry,
)


# ════════════════════════════════════════════
# FormulaEntry tests
# ════════════════════════════════════════════


class TestFormulaEntry:
    def test_create_minimal(self):
        """Create entry with minimum fields."""
        e = FormulaEntry(fid="eq:test", latex=r"E = mc^2")
        assert e.fid == "eq:test"
        assert e.verification_status == "unverified"
        assert e.registry_schema_version == CURRENT_SCHEMA_VERSION

    def test_create_full(self):
        """Create entry with all fields."""
        e = FormulaEntry(
            fid="eq:biot-savart",
            latex=r"B = \frac{\mu_0 I}{4\pi d}",
            sympy="mu0*I/(4*pi*d)",
            source_keys=["Griffiths2023"],
            extracted_from="sf_12345",
            equation_index=42,
            pint_dimension="magnetic flux density",
            verification_status="verified",
            verified_at="2026-01-01T00:00:00+00:00",
            expires_at="2027-01-01T00:00:00+00:00",
            tags=["magnetostatics", "biot-savart"],
        )
        assert e.fid == "eq:biot-savart"
        assert len(e.verifications) == 0
        assert e.is_verified

    def test_serialize_roundtrip(self):
        """to_dict → from_dict should preserve all fields."""
        e1 = FormulaEntry(
            fid="eq:test", latex=r"x = y",
            source_keys=["Ref1"],
            tags=["physics"],
        )
        d = e1.to_dict()
        e2 = FormulaEntry.from_dict(d)
        assert e2.fid == e1.fid
        assert e2.latex == e1.latex
        assert e2.source_keys == e1.source_keys
        assert e2.tags == e1.tags
        assert e2.registry_schema_version == CURRENT_SCHEMA_VERSION

    def test_is_expired(self):
        """Entry with past expiry is expired."""
        e = FormulaEntry(
            fid="eq:old", latex=r"x=1",
            verification_status="verified",
            verified_at="2020-01-01T00:00:00+00:00",
            expires_at="2020-06-01T00:00:00+00:00",
        )
        assert e.is_expired
        assert not e.is_verified

    def test_is_not_expired(self):
        """Entry with future expiry is not expired."""
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        e = FormulaEntry(
            fid="eq:new", latex=r"x=1",
            verification_status="verified",
            verified_at=datetime.now(timezone.utc).isoformat(),
            expires_at=future,
        )
        assert not e.is_expired
        assert e.is_verified

    def test_mark_verified(self):
        """mark_verified() updates status and sets TTL."""
        e = FormulaEntry(fid="eq:t", latex=r"y=2x")
        e.mark_verified(layer="L1", detail="symbolic pass")
        assert e.verification_status == "verified"
        assert e.verified_at is not None
        assert e.expires_at is not None
        assert len(e.verifications) == 1
        assert e.verifications[0]["layer"] == "L1"
        assert e.verifications[0]["passed"] is True

    def test_mark_failed(self):
        """mark_failed() sets status to failed."""
        e = FormulaEntry(fid="eq:f", latex=r"z=0")
        e.mark_failed(layer="L2", detail="numerical mismatch")
        assert e.verification_status == "failed"
        assert len(e.verifications) == 1
        assert e.verifications[0]["layer"] == "L2"
        assert e.verifications[0]["passed"] is False


# ════════════════════════════════════════════
# FormulaRegistry CRUD tests
# ════════════════════════════════════════════


@pytest.fixture
def tmp_registry():
    """Create a temporary FormulaRegistry backed by a temp file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test_registry.jsonl"
        reg = FormulaRegistry(path=path)
        yield reg


class TestFormulaRegistry:
    def test_empty_registry(self, tmp_registry):
        """New registry has no entries."""
        assert tmp_registry.count() == 0
        assert tmp_registry.load_all() == []

    def test_add_and_get(self, tmp_registry):
        """Add an entry and retrieve by fid."""
        e = FormulaEntry(fid="eq:mc2", latex=r"E=mc^2")
        assert tmp_registry.add(e) is True
        assert tmp_registry.count() == 1

        retrieved = tmp_registry.get("eq:mc2")
        assert retrieved is not None
        assert retrieved.fid == "eq:mc2"
        assert retrieved.latex == r"E=mc^2"

    def test_duplicate_fid_rejected(self, tmp_registry):
        """Adding same fid twice returns False."""
        e1 = FormulaEntry(fid="eq:dup", latex=r"a=b")
        e2 = FormulaEntry(fid="eq:dup", latex=r"c=d")
        assert tmp_registry.add(e1) is True
        assert tmp_registry.add(e2) is False  # duplicate rejected

    def test_update_fields(self, tmp_registry):
        """Update entry fields in memory."""
        e = FormulaEntry(fid="eq:upd", latex=r"x=1")
        tmp_registry.add(e)
        assert tmp_registry.update("eq:upd", latex=r"x=2") is True
        assert tmp_registry.get("eq:upd").latex == r"x=2"

    def test_update_nonexistent(self, tmp_registry):
        """Updating non-existent fid returns False."""
        assert tmp_registry.update("eq:ghost", latex=r"nope") is False

    def test_remove(self, tmp_registry):
        """Remove an entry."""
        e = FormulaEntry(fid="eq:rem", latex=r"x=1")
        tmp_registry.add(e)
        assert tmp_registry.count() == 1
        assert tmp_registry.remove("eq:rem") is True
        assert tmp_registry.count() == 0
        assert tmp_registry.get("eq:rem") is None

    def test_remove_nonexistent(self, tmp_registry):
        """Removing non-existent fid returns False."""
        assert tmp_registry.remove("eq:ghost") is False

    def test_save_and_reload(self, tmp_registry):
        """Save to disk and reload preserves entries."""
        e1 = FormulaEntry(fid="eq:a", latex=r"a=b", tags=["test"])
        e2 = FormulaEntry(fid="eq:b", latex=r"c=d", tags=["test"])
        tmp_registry.add(e1)
        tmp_registry.add(e2)
        tmp_registry.save()

        # Create a new registry instance pointing to same file
        reg2 = FormulaRegistry(path=tmp_registry.path)
        assert reg2.count() == 2
        assert reg2.get("eq:a").latex == r"a=b"
        assert reg2.get("eq:b").latex == r"c=d"

    def test_query_by_status(self, tmp_registry):
        """Filter entries by verification status."""
        e1 = FormulaEntry(fid="eq:v", latex=r"x=1", verification_status="verified")
        e2 = FormulaEntry(fid="eq:u", latex=r"y=2", verification_status="unverified")
        e3 = FormulaEntry(fid="eq:f", latex=r"z=3", verification_status="failed")
        for e in (e1, e2, e3):
            tmp_registry.add(e)

        verified = tmp_registry.get_by_status("verified")
        assert len(verified) == 1
        assert verified[0].fid == "eq:v"

        unverified = tmp_registry.get_by_status("unverified")
        assert len(unverified) == 1
        assert unverified[0].fid == "eq:u"

    def test_query_by_tag(self, tmp_registry):
        """Filter entries by tag."""
        e1 = FormulaEntry(fid="eq:a", latex=r"x=1", tags=["magnetostatics"])
        e2 = FormulaEntry(fid="eq:b", latex=r"y=1", tags=["optics"])
        e3 = FormulaEntry(fid="eq:c", latex=r"z=1", tags=["magnetostatics", "biot-savart"])
        for e in (e1, e2, e3):
            tmp_registry.add(e)

        magneto = tmp_registry.get_by_tag("magnetostatics")
        assert len(magneto) == 2

        optics = tmp_registry.get_by_tag("optics")
        assert len(optics) == 1

    def test_get_unverified(self, tmp_registry):
        """get_unverified() returns unverified + expired entries."""
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        past = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        e1 = FormulaEntry(fid="eq:u", latex=r"x=1", verification_status="unverified")
        e2 = FormulaEntry(
            fid="eq:v", latex=r"x=2", verification_status="verified",
            verified_at=future, expires_at=future,
        )
        e3 = FormulaEntry(
            fid="eq:e", latex=r"x=3", verification_status="verified",
            verified_at=past, expires_at=past,
        )
        for e in (e1, e2, e3):
            tmp_registry.add(e)

        unv = tmp_registry.get_unverified()
        fids = {e.fid for e in unv}
        assert "eq:u" in fids  # unverified
        assert "eq:e" in fids  # expired
        assert "eq:v" not in fids  # still valid

    def test_stats(self, tmp_registry):
        """stats() returns correct counts."""
        e1 = FormulaEntry(fid="eq:a", latex=r"x=1", verification_status="verified")
        e2 = FormulaEntry(fid="eq:b", latex=r"x=2", verification_status="unverified")
        tmp_registry.add(e1)
        tmp_registry.add(e2)

        s = tmp_registry.stats()
        assert s["total"] == 2
        assert s["by_status"]["verified"] == 1
        assert s["by_status"]["unverified"] == 1

    def test_invalid_jsonl_line_skipped(self):
        """Corrupted lines in JSONL are skipped gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "corrupt.jsonl"
            path.write_text(
                '{"fid": "good", "latex": "x=y"}\n'
                'not-json\n'
                '{"fid": "ok", "latex": "a=b"}\n',
            )
            reg = FormulaRegistry(path=path)
            assert reg.count() == 2
            assert reg.get("good") is not None
            assert reg.get("ok") is not None

    def test_get_by_source(self, tmp_registry):
        """Filter formulas by source paper sf_id."""
        e1 = FormulaEntry(fid="eq:a", latex=r"x=1", extracted_from="sf_001")
        e2 = FormulaEntry(fid="eq:b", latex=r"x=2", extracted_from="sf_002")
        e3 = FormulaEntry(fid="eq:c", latex=r"x=3", extracted_from="sf_001")
        for e in (e1, e2, e3):
            tmp_registry.add(e)

        from_sf001 = tmp_registry.get_by_source("sf_001")
        assert len(from_sf001) == 2

        from_sf002 = tmp_registry.get_by_source("sf_002")
        assert len(from_sf002) == 1

    def test_get_nonexistent(self, tmp_registry):
        """Getting non-existent fid returns None."""
        assert tmp_registry.get("eq:ghost") is None

    def test_add_upgrades_schema(self, tmp_registry):
        """Old schema version gets auto-upgraded on add."""
        old = FormulaEntry(
            fid="eq:old",
            latex=r"x=y",
            registry_schema_version=0,
        )
        tmp_registry.add(old)
        assert tmp_registry.get("eq:old").registry_schema_version == CURRENT_SCHEMA_VERSION
