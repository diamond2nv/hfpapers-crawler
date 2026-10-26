#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# test_invariants_network.py
"""The DOI title check: what it must see, and what it must not call a mismatch.

Both defects below were found in the live store on 2026-09-25 while re-running a LAN peer's
low-confidence-DOI audit from this side; each one made a *correct* DOI look like a
different paper. Network access is always stubbed — a gate that needs the internet is
not a gate (see `invariants.py`).
"""

import difflib
import os
import tempfile

import pytest

from hfpapers import invariants_network as inv_net
from hfpapers.paper_store import PaperRecord, PaperStore

# Live examples. Titles are facts about published works; no personal data.
PRL_RECORD = "High-beta equilibria of drift-optimized compact stellarators"
PRL_CROSSREF = (
    'High-<mml:math xmlns:mml="http://www.w3.org/1998/Math/MathML" display="inline">'
    "<mml:mi>β</mml:mi></mml:math>Equilibria of Drift-Optimized Compact Stellarators"
)
APA_RECORD = "铁磁板磁巴克豪森应力检测的解析模型"
APA_CROSSREF = "Analytical model of magnetic Barkhausen stress test of ferromagnetic plates"


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, inv_net._norm(a), inv_net._norm(b)).ratio()


@pytest.fixture
def store_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "papers.db")


def _store_with(store_path: str, title: str) -> tuple[PaperStore, dict]:
    store = PaperStore(db_path=store_path)
    sf_id = store.upsert_paper(PaperRecord(title=title, year=2024))
    ids = {sf_id: [("doi", "10.1000/x", 1.0, "test")]}
    return store, ids


class TestNormalisation:
    def test_inline_mathml_does_not_eat_the_character_budget(self):
        # 0.165 before the fix: the MathML blob occupied the first 80 normalised characters,
        # so the comparison ran against markup instead of the title.
        assert _ratio(PRL_RECORD, PRL_CROSSREF) > 0.90

    def test_entities_are_unescaped(self):
        assert _ratio("Magnet R&D for the Muon Collider", "Magnet R&amp;D for the Muon Collider") > 0.95

    def test_cjk_title_is_not_normalised_to_nothing(self):
        assert inv_net._norm(APA_RECORD) != ""

    def test_punctuation_and_case_still_fold(self):
        assert inv_net._norm("DeepONet: A Library!") == inv_net._norm("deeponet a library")


class TestCrossLanguageTitles:
    def test_cjk_record_against_english_doi_title_is_skipped_not_mismatched(
        self, store_path, monkeypatch
    ):
        # The ratio measures the comparison, not the data: Crossref only carries the English
        # title, so any threshold deletes a Chinese journal paper.
        store, ids = _store_with(store_path, APA_RECORD)
        monkeypatch.setattr(inv_net, "_crossref_title", lambda doi, timeout=25: APA_CROSSREF)
        findings, checked, unreachable, cross_language = inv_net.check_doi_titles(
            store, ids, sleep=0
        )
        assert findings == []
        assert (checked, unreachable, cross_language) == (0, 0, 1)

    def test_both_sides_cjk_is_still_compared(self, store_path, monkeypatch):
        store, ids = _store_with(store_path, "铁磁板磁巴克豪森应力检测的解析模型")
        monkeypatch.setattr(
            inv_net, "_crossref_title", lambda doi, timeout=25: "铁磁扭摆振子磁传感器的探测性能"
        )
        findings, checked, _unreachable, cross_language = inv_net.check_doi_titles(
            store, ids, sleep=0
        )
        assert checked == 1 and cross_language == 0
        assert [f.check for f in findings] == ["doi.title_mismatch"]


class TestTheFixDoesNotSilenceRealFindings:
    def test_two_different_english_papers_are_still_reported(self, store_path, monkeypatch):
        store, ids = _store_with(store_path, "High-beta equilibria of drift-optimized compact stellarators")
        monkeypatch.setattr(
            inv_net,
            "_crossref_title",
            lambda doi, timeout=25: "Kinetic Damping of Toroidal Alfven Eigenmodes",
        )
        findings, checked, _unreachable, cross_language = inv_net.check_doi_titles(
            store, ids, sleep=0
        )
        assert checked == 1 and cross_language == 0
        assert [f.check for f in findings] == ["doi.title_mismatch"]
        assert findings[0].severity == "error"

    def test_mathml_match_produces_no_finding(self, store_path, monkeypatch):
        store, ids = _store_with(store_path, PRL_RECORD)
        monkeypatch.setattr(inv_net, "_crossref_title", lambda doi, timeout=25: PRL_CROSSREF)
        findings, checked, _unreachable, cross = inv_net.check_doi_titles(store, ids, sleep=0)
        assert (findings, checked, cross) == ([], 1, 0)

    def test_unreachable_crossref_is_counted_not_reported(self, store_path, monkeypatch):
        store, ids = _store_with(store_path, PRL_RECORD)
        monkeypatch.setattr(inv_net, "_crossref_title", lambda doi, timeout=25: None)
        findings, checked, unreachable, _cross = inv_net.check_doi_titles(store, ids, sleep=0)
        assert findings == [] and (checked, unreachable) == (0, 1)
