#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# test_doi_write_gate.py
"""A DOI a caller hands over is looked up before it is written (v0.19.10).

Written from the failure it exists to catch: on 2026-09-25 a full audit of the live store found
three wrong DOIs, and **all three arrived through the supplied-DOI path** — `add_identifier` wrote
them at its default `confidence=1.0`, so nothing ever asked a registry what they pointed at. One of
them (`10.1038/s41467-024-51582-9`) is registered with neither Crossref nor DataCite.

Network is always stubbed.  "Could not check" must stay distinguishable from "wrong" — the audit's
own ``FETCH_FAIL`` lesson, applied to the write path.
"""

import os
import tempfile

import pytest

from hfpapers import doi_registry
from hfpapers.paper_store import PaperRecord, PaperStore

MATCHING = "Quasi-single-stage optimization for permanent magnet stellarators"
OTHER_PAPER = "Kinetic Damping of Toroidal Alfven Eigenmodes"
CJK_TITLE = "铁磁板磁巴克豪森应力检测的解析模型"
MATHML_TITLE = ('High-<mml:math xmlns:mml="http://www.w3.org/1998/Math/MathML" display="inline">'
                "<mml:mi>β</mml:mi></mml:math>Equilibria of Drift-Optimized Compact Stellarators")


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield PaperStore(db_path=os.path.join(tmpdir, "papers.db"))


def _record(store: PaperStore, title: str) -> int:
    return store.upsert_paper(PaperRecord(title=title, year=2024))


def _events(store: PaperStore, sf_id: int) -> list[tuple[str, str]]:
    with store._lock, store._conn() as conn:  # noqa: SLF001 — test inspects the row-level log
        rows = conn.execute(
            "SELECT kind, reason FROM store_events WHERE sf_id=? ORDER BY id", (sf_id,)
        ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _dois(store: PaperStore, sf_id: int) -> list[str]:
    with store._lock, store._conn() as conn:  # noqa: SLF001
        return [r[0] for r in conn.execute(
            "SELECT id_value FROM identifiers WHERE sf_id=? AND id_type='doi'", (sf_id,))]


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class TestResolve:
    def test_crossref_answer_wins(self, monkeypatch):
        monkeypatch.setattr(doi_registry.requests, "get", lambda *a, **k: _Resp(200, {"message": {
            "title": [MATCHING], "container-title": ["Nuclear Fusion"],
            "issued": {"date-parts": [[2024]]}, "type": "journal-article"}}))
        status, work = doi_registry.resolve("10.1000/x")
        assert status == "ok" and work["registry"] == "crossref" and work["title"] == MATCHING

    def test_crossref_404_falls_through_to_datacite(self, monkeypatch):
        # A Crossref 404 is not evidence that the DOI is bogus: arXiv/Zenodo/CNKI DOIs live in
        # DataCite, and the live store holds 20 of them.
        def fake_get(url, **kwargs):
            if "crossref" in url:
                return _Resp(404)
            return _Resp(200, {"data": {"attributes": {
                "titles": [{"title": MATHML_TITLE}], "publisher": "arXiv",
                "publicationYear": 2023, "types": {"resourceTypeGeneral": "Preprint"}}}})

        monkeypatch.setattr(doi_registry.requests, "get", fake_get)
        status, work = doi_registry.resolve("10.48550/arXiv.2406.04692")
        assert status == "ok"
        assert work["registry"] == "datacite"
        assert "<mml:math" not in work["title"]  # markup stripped, so a caller can compare titles

    def test_unknown_in_both_registries_is_not_found(self, monkeypatch):
        monkeypatch.setattr(doi_registry.requests, "get", lambda *a, **k: _Resp(404))
        assert doi_registry.resolve("10.1038/s41467-024-51582-9") == ("not_found", {})

    def test_unreachable_registry_is_an_error_not_a_verdict(self, monkeypatch):
        def boom(*a, **k):
            raise doi_registry.requests.RequestException("no route to host")

        monkeypatch.setattr(doi_registry.requests, "get", boom)
        status, work = doi_registry.resolve("10.1000/x")
        assert status == "error" and work["reason"]


class TestAttachSuppliedDoi:
    def test_matching_title_is_attached(self, store, monkeypatch):
        sf = _record(store, MATCHING)
        monkeypatch.setattr(doi_registry, "resolve", lambda doi, **k: ("ok", {"title": MATCHING, "registry": "crossref"}))
        assert store.attach_supplied_doi(sf, "10.1000/ok", MATCHING, source="test") == "attached"
        assert _dois(store, sf) == ["10.1000/ok"]

    def test_markup_in_the_registry_title_does_not_block_a_match(self, store, monkeypatch):
        sf = _record(store, "High-beta equilibria of drift-optimized compact stellarators")
        monkeypatch.setattr(doi_registry, "resolve", lambda doi, **k: ("ok", {"title": MATHML_TITLE, "registry": "crossref"}))
        assert store.attach_supplied_doi(sf, "10.1000/ok", "High-beta equilibria of drift-optimized compact stellarators") == "attached"

    def test_unregistered_doi_is_refused_and_recorded(self, store, monkeypatch):
        sf = _record(store, "Parallel quantum computing with NV centers in diamond")
        monkeypatch.setattr(doi_registry, "resolve", lambda doi, **k: ("not_found", {}))
        assert store.attach_supplied_doi(sf, "10.1038/s41467-024-51582-9", "Parallel quantum computing") == "refused"
        assert _dois(store, sf) == []
        kinds = [k for k, _ in _events(store, sf)]
        assert "identifier_rejected" in kinds

    def test_wrong_paper_is_refused_with_the_registry_title(self, store, monkeypatch):
        sf = _record(store, "A physically motivated analytical expression for the zero-field splitting")
        monkeypatch.setattr(doi_registry, "resolve", lambda doi, **k: ("ok", {"title": OTHER_PAPER, "registry": "crossref"}))
        assert store.attach_supplied_doi(sf, "10.1103/PhysRevB.107.214110", "A physically motivated analytical expression") == "refused"
        assert _dois(store, sf) == []

    def test_explicit_acceptance_still_admits_a_mismatch(self, store, monkeypatch):
        sf = _record(store, "A physically motivated analytical expression for the zero-field splitting")
        monkeypatch.setattr(doi_registry, "resolve", lambda doi, **k: ("ok", {"title": OTHER_PAPER, "registry": "crossref"}))
        assert store.attach_supplied_doi(sf, "10.1000/x", "A physically motivated expression", accept_unverified=True) == "attached"
        assert _dois(store, sf) == ["10.1000/x"]

    def test_unreachable_registry_writes_the_doi_and_says_it_is_unchecked(self, store, monkeypatch):
        sf = _record(store, MATCHING)
        monkeypatch.setattr(doi_registry, "resolve", lambda doi, **k: ("error", {"reason": "timeout"}))
        assert store.attach_supplied_doi(sf, "10.1000/ok", MATCHING, source="orcid") == "unchecked"
        assert _dois(store, sf) == ["10.1000/ok"]
        kinds = [k for k, _ in _events(store, sf)]
        assert "identifier_unverified" in kinds

    def test_cjk_record_against_an_english_registry_title_is_unchecked_not_refused(self, store, monkeypatch):
        # 0.00 similarity would refuse a correct Chinese journal DOI under the mismatch rule.
        sf = _record(store, CJK_TITLE)
        monkeypatch.setattr(doi_registry, "resolve", lambda doi, **k: ("ok", {"title": "Analytical model of magnetic Barkhausen stress test", "registry": "crossref"}))
        assert store.attach_supplied_doi(sf, "10.7498/aps.71.20212253", CJK_TITLE) == "unchecked"
        assert _dois(store, sf) == ["10.7498/aps.71.20212253"]

    def test_record_without_a_title_cannot_be_checked(self, store, monkeypatch):
        sf = _record(store, "")
        monkeypatch.setattr(doi_registry, "resolve", lambda doi, **k: ("ok", {"title": MATCHING, "registry": "crossref"}))
        assert store.attach_supplied_doi(sf, "10.1000/ok", "") == "unchecked"


class TestNearNeighbourBar:
    """0.5 was chosen from the store, not from taste (see `SUPPLIED_DOI_MIN_SIMILARITY`).

    Measured over the 310 DOI↔title pairs the 2026-09-25 audit called correct: none below 0.45,
    two below 0.5.  The different-OSTI-report pair in the same field scores 0.44 — the case the bar
    exists for.
    """

    def test_a_same_field_near_neighbour_is_refused(self, store, monkeypatch):
        stored = "Evidence of coupling between toroidal Alfven eigenmodes and kinetic Alfven waves"
        sf = _record(store, stored)
        monkeypatch.setattr(doi_registry, "resolve", lambda doi, **k: (
            "ok", {"title": "Kinetic Damping of Toroidal Alfven Eigenmodes", "registry": "crossref"}))
        assert store.attach_supplied_doi(sf, "10.2172/839535", stored) == "refused"
        assert _dois(store, sf) == []

    def test_a_format_variant_of_the_same_paper_still_passes(self, store, monkeypatch):
        stored = ("FULLY 3-DIMENSIONAL IDEAL MAGNETOHYDRODYNAMIC STABILITY ANALYSIS OF "
                  "TOROIDAL PLASMAS WITH FLOW")
        sf = _record(store, stored)
        monkeypatch.setattr(doi_registry, "resolve", lambda doi, **k: (
            "ok", {"title": "Fully three-dimensional ideal magnetohydrodynamic stability analysis "
                            "of toroidal plasmas with flow", "registry": "crossref"}))
        assert store.attach_supplied_doi(sf, "10.1063/1.860100", stored) == "attached"


class TestEnsurePaperRouting:
    def test_supplied_doi_goes_through_the_gate(self, monkeypatch):
        import hfpapers.paper_store as ps

        with tempfile.TemporaryDirectory() as tmpdir:
            ps._store_instance = PaperStore(db_path=os.path.join(tmpdir, "papers.db"))
            monkeypatch.setattr(doi_registry, "resolve", lambda doi, **k: ("not_found", {}))
            sf, _new = ps.ensure_paper("", doi="10.1038/s41467-024-51582-9",
                                       title="Parallel quantum computing with NV centers in diamond")
            assert _dois(ps._store_instance, sf) == []
            ps._store_instance = None

    def test_verify_doi_false_keeps_the_offline_path_writing(self, monkeypatch):
        import hfpapers.paper_store as ps

        def explode(*a, **k):
            raise AssertionError("resolve() must not be called when verify_doi=False")

        with tempfile.TemporaryDirectory() as tmpdir:
            ps._store_instance = PaperStore(db_path=os.path.join(tmpdir, "papers.db"))
            monkeypatch.setattr(doi_registry, "resolve", explode)
            sf, _new = ps.ensure_paper("", doi="10.1000/off", title="Anything", verify_doi=False)
            assert _dois(ps._store_instance, sf) == ["10.1000/off"]
            ps._store_instance = None


class TestStoreScopedHealthCheck:
    def test_only_sf_ids_limits_findings_to_this_run(self, store):
        from hfpapers.invariants import check_store

        bad = store.upsert_paper(PaperRecord(title="", year=0))          # title.empty
        store.upsert_paper(PaperRecord(title="A Good Paper", year=2024))
        whole = check_store(store)
        scoped = check_store(store, only_sf_ids={bad})
        assert any(f.subject == str(bad) for f in whole.findings)
        assert {f.subject for f in scoped.findings} == {str(bad)}
        assert scoped.coverage["papers"] == whole.coverage["papers"]
