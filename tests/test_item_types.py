#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# test_item_types.py
"""Item types — vocabulary, derivation rules, and the store surface around them.

The derivation cases are drawn from real records in this store, including three
mis-derivations found while backfilling (``synthesis`` firing the thesis marker,
``hypothesis`` doing the same, and an ICLR-under-review venue being read as a conference).
Those three are the regression tests that matter most: they were wrong in production.
"""

import os
import sqlite3
import tempfile

import pytest

from hfpapers.item_types import (
    DERIVED_TYPES,
    ITEM_TYPES,
    coerce_item_type,
    derive_item_type,
    is_peer_reviewed,
    normalise_item_type,
)


class TestVocabulary:
    def test_names_match_keys(self):
        for name, spec in ITEM_TYPES.items():
            assert spec.name == name, f"{name} has a mismatched spec name"

    def test_unknown_is_our_extension_and_not_derived(self):
        assert "unknown" in ITEM_TYPES
        assert ITEM_TYPES["unknown"].in_zotero is False
        assert ITEM_TYPES["unknown"].peer_reviewed is None
        assert "unknown" not in DERIVED_TYPES

    def test_every_derived_type_is_a_zotero_name(self):
        # The point of borrowing Zotero's vocabulary: a derived name maps without translation.
        for name in DERIVED_TYPES:
            assert ITEM_TYPES[name].in_zotero is True

    def test_peer_reviewed_is_explicit(self):
        assert is_peer_reviewed("journalArticle") is True
        assert is_peer_reviewed("conferencePaper") is True
        assert is_peer_reviewed("preprint") is False
        assert is_peer_reviewed("report") is False
        assert is_peer_reviewed("not-a-type") is None


class TestNormalisation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("journalArticle", "journalArticle"),
            ("Journal", "journalArticle"),
            ("arXiv", "preprint"),
            ("whitepaper", "report"),
            ("Technical Report", "report"),
            ("dissertation", "thesis"),
        ],
    )
    def test_aliases(self, raw, expected):
        assert normalise_item_type(raw) == expected

    def test_blank_stays_blank(self):
        assert normalise_item_type("") == ""
        assert normalise_item_type("   ") == ""

    def test_unknown_name_is_rejected_or_empty(self):
        assert normalise_item_type("misc") == ""
        with pytest.raises(ValueError):
            coerce_item_type("misc")


class TestDerivation:
    @pytest.mark.parametrize(
        "kwargs,expected,reason_prefix",
        [
            # ── editorial markers first ──────────────────────────────────────
            (
                {"venue": "Technical Report", "tags": ["not-peer-reviewed"]},
                "report",
                "tag:not-peer-reviewed",
            ),
            ({"venue": "OSTI Technical Report"}, "report", "venue~technical report"),
            ({"venue": "", "title": "A Study of Widgets (PhD thesis)"}, "thesis", "thesis-marker"),
            ({"venue": "Some Conference Blog"}, "webpage", "venue~blog"),
            # ── not-yet-published outranks a conference acronym ──────────────
            (
                {"venue": "arXiv:2508.04349 (ICLR 2026 under review)", "id_types": ["arxiv"]},
                "preprint",
                "venue~under review",
            ),
            ({"venue": "arXiv preprint", "id_types": ["arxiv"]}, "preprint", "venue~preprint"),
            # ── refereed containers ─────────────────────────────────────────
            ({"venue": "ACL 2026", "id_types": ["doi"]}, "conferencePaper", "venue~acl"),
            ({"venue": "NeurIPS 2025", "id_types": ["doi"]}, "conferencePaper", "venue~neurips"),
            (
                {"venue": "Advances in Neural Information Processing Systems 38", "id_types": ["doi"]},
                "conferencePaper",
                "venue~advances in neural information processing systems",
            ),
            ({"venue": "Nature", "id_types": ["doi"]}, "journalArticle", "doi + venue:Nature"),
            ({"venue": "", "id_types": ["doi"]}, "journalArticle", "doi"),
            # ── arXiv shapes ────────────────────────────────────────────────
            ({"venue": "arXiv", "id_types": ["arxiv"]}, "preprint", "arxiv-venue"),
            ({"venue": "physics.plasm-ph", "id_types": ["arxiv"]}, "preprint", "arxiv-category-as-venue"),
            (
                {"venue": "cond-mat.mtrl-sci, physics.comp-ph", "id_types": ["arxiv"]},
                "preprint",
                "arxiv-category-as-venue",
            ),
            ({"venue": "", "id_types": ["arxiv"]}, "preprint", "no-venue"),
            ({"venue": "", "id_types": []}, "unknown", "no rule matched"),
            ({"venue": "Wharton Faculty Page", "id_types": ["url"]}, "webpage", "url-only"),
        ],
    )
    def test_rules(self, kwargs, expected, reason_prefix):
        name, reason = derive_item_type(**kwargs)
        assert name == expected, f"{kwargs} → {name} ({reason})"
        assert reason.startswith(reason_prefix), reason

    # ── the three production mis-derivations, as regression tests ───────────
    def test_synthesis_is_not_a_thesis(self):
        name, _ = derive_item_type(
            venue="npj Computational Materials (arXiv preprint)",
            title="ProvMind: provenance-grounded reasoning for materials synthesis",
        )
        assert name == "preprint"

    def test_hypothesis_is_not_a_thesis(self):
        name, reason = derive_item_type(
            venue="",
            title="LLM-PDESR: Robust PDE Discovery via Subdomain Weighted Residuals "
            "and LLM-Guided Symbolic Hypothesis Generation",
            id_types=["arxiv"],
        )
        assert name == "preprint", reason
        assert "thesis" not in reason

    def test_acronyms_are_word_bounded(self):
        # "Oracle" contains "acl"; a venue must not be read as ACL on a substring hit.
        name, _ = derive_item_type(venue="Oracle Labs Quarterly", id_types=["doi"])
        assert name == "journalArticle"

    def test_reason_is_never_empty(self):
        for kwargs in ({}, {"venue": "Nature", "id_types": ["doi"]}, {"venue": "arXiv", "id_types": ["arxiv"]}):
            _, reason = derive_item_type(**kwargs)
            assert reason, f"no reason for {kwargs}"


class TestStoreSurface:
    def _store(self, tmpdir):
        from hfpapers.paper_store import PaperStore

        return PaperStore(db_path=os.path.join(tmpdir, "papers.db"))

    def test_migration_adds_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)  # _init_db runs on construction
            with sqlite3.connect(store.db_path) as conn:
                cols = {row[1] for row in conn.execute("PRAGMA table_info(papers)")}
            assert {"item_type", "item_type_src", "item_type_at"} <= cols

    def test_set_and_get_roundtrip(self):
        from hfpapers.paper_store import PaperRecord

        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="Paper A", source="test"))
            assert store.get_item_type(sf) == ("", "")

            store.set_item_type(sf, "arXiv")  # alias accepted
            name, src = store.get_item_type(sf)
            assert name == "preprint" and src == "manual"

            store.set_item_type(sf, "journalArticle", src="derived")
            assert store.get_item_type(sf) == ("journalArticle", "derived")

    def test_stats_split_never_classified_from_no_rule(self):
        from hfpapers.paper_store import PaperRecord

        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            a = store.upsert_paper(PaperRecord(title="A", source="test"))
            b = store.upsert_paper(PaperRecord(title="B", source="test"))
            store.upsert_paper(PaperRecord(title="C", source="test"))
            store.set_item_type(a, "preprint", src="derived")
            store.set_item_type(b, "unknown", src="derived")
            stats = store.item_type_stats()
            assert stats["total"] == 3
            assert stats["by_type"]["preprint"] == 1
            assert stats["never_classified"] == 1  # c
            assert stats["no_rule_matched"] == 1  # b
            assert stats["by_source"]["derived"] == 2

    def test_backfill_inputs_carry_identifiers_and_tags(self):
        from hfpapers.paper_store import PaperRecord

        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="Tagged paper", venue="Nature"))
            store.add_identifier(sf, "doi", "10.1000/x", source="test")
            store.add_identifier(sf, "tag", "not-peer-reviewed", source="test")
            rows = store.iter_item_type_inputs()
            assert len(rows) == 1
            assert rows[0]["sf_id"] == sf
            assert "doi" in rows[0]["id_types"]
            assert "not-peer-reviewed" in rows[0]["tags"]
            # Classifying it removes it from the default pass.
            store.set_item_type(sf, "report", src="derived")
            assert store.iter_item_type_inputs() == []

    def test_coverage_flags_names_outside_the_vocabulary(self):
        from hfpapers.paper_store import PaperRecord

        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="A", source="test"))
            store.set_item_type(sf, "preprint")
            assert store.item_type_coverage()["unknown_names"] == []
            with sqlite3.connect(store.db_path) as conn:  # simulate a pre-vocabulary value
                conn.execute("UPDATE papers SET item_type='misc' WHERE sf_id=?", (sf,))
            assert store.item_type_coverage()["unknown_names"] == ["misc"]
