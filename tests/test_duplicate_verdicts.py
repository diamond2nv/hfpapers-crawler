#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# test_duplicate_verdicts.py
"""What a duplicate-identity pair *is* — decided by evidence, not by identifier count (v0.19.12).

Written from the pair this replaces: two records shared a title, both held a DOI, and the offline rule
("overlapping kinds ⇒ two artefacts of one work") left a DOI that described a different paper in the
store while the correct copy was the one a human would have dropped.  Encoding the verdicts here keeps
`store dedup`, the audit and the write guard telling the same story.

The network half is stubbed: `_norm`-level comparison is exercised through `doi_matches_title`'s callers
with the answer supplied, so the tests stay offline and deterministic.
"""

from __future__ import annotations

import tempfile

import pytest

from hfpapers.invariants import (
    DUPLICATE_VERDICTS,
    DuplicateMember,
    classify_duplicate_pair,
    plan_duplicate_group,
)
from hfpapers.paper_store import PaperStore

TITLE = "Evidence of coupling between toroidal Alfven eigenmodes and kinetic Alfven waves"


def _member(sf_id: int, *, kinds=("doi",), year: int = 0, matches: bool | None = None, title=TITLE):
    return DuplicateMember(sf_id, title, year, frozenset(kinds), matches)


class TestClassifyPair:
    def test_offline_kind_split_is_a_merge(self):
        """One copy with the DOI and one with the arXiv id — the shape `store dedup` was built for."""
        keep = _member(1, kinds=("doi",))
        drop = _member(2, kinds=("arxiv",))
        assert classify_duplicate_pair(keep, drop) == "mergeable"

    def test_a_strict_subset_copy_stays_manual(self):
        """Parity with the pre-0.19.12 rule: overlapping kinds never auto-merge, even as a subset."""
        keep = _member(1, kinds=("doi", "arxiv"))
        drop = _member(2, kinds=("arxiv",))
        assert classify_duplicate_pair(keep, drop) == "human"

    def test_different_titles_are_not_the_same_work(self):
        keep = _member(1)
        drop = _member(2, title="Kinetic Damping of Toroidal Alfven Eigenmodes")
        assert classify_duplicate_pair(keep, drop) == "not_same_work"

    def test_two_verified_dois_are_a_version_pair(self):
        """Journal paper plus its OSTI report: both DOIs describe this title, both are kept."""
        verdict = classify_duplicate_pair(_member(1, matches=True), _member(2, matches=True))
        assert verdict == "version_pair"

    def test_one_wrong_doi_is_named_wrong(self):
        """The live 2026-09-25 shape: the drop candidate's DOI describes another paper."""
        verdict = classify_duplicate_pair(_member(1, matches=True), _member(2, matches=False))
        assert verdict == "drop_wrong_doi"

    def test_overlapping_kinds_without_evidence_stays_manual(self):
        verdict = classify_duplicate_pair(_member(1, matches=None), _member(2, matches=None))
        assert verdict == "human"

    def test_every_verdict_is_declared(self):
        assert classify_duplicate_pair(_member(1), _member(2, title="x")) in DUPLICATE_VERDICTS


class TestPlanGroup:
    def test_a_richer_wrong_copy_is_not_kept(self):
        """Ranking must not be "most identifiers wins" — the wrong copy held the DOI in the real pair."""
        wrong = _member(7, kinds=("doi", "tag"), matches=False)
        right = _member(9, kinds=("doi",), matches=True)
        keep, drops = plan_duplicate_group([wrong, right])
        assert keep.sf_id == 9
        assert [(d.sf_id, v) for d, v in drops] == [(7, "drop_wrong_doi")]

    def test_ties_break_on_identifier_count_then_id(self):
        keep, drops = plan_duplicate_group([_member(5, kinds=("doi",)), _member(4, kinds=("arxiv",))])
        assert keep.sf_id == 4
        assert drops[0][1] == "mergeable"

    def test_more_identifiers_wins_when_evidence_is_equal(self):
        keep, drops = plan_duplicate_group([_member(1, kinds=("doi",)), _member(2, kinds=("doi", "tag"))])
        assert keep.sf_id == 2
        assert drops[0][0].sf_id == 1

    def test_single_member_group_has_no_drops(self):
        keep, drops = plan_duplicate_group([_member(1)])
        assert keep is not None and keep.sf_id == 1 and drops == []

    def test_empty_group(self):
        assert plan_duplicate_group([]) == (None, [])


@pytest.fixture()
def store():
    with tempfile.TemporaryDirectory() as tmp:
        yield PaperStore(db_path=f"{tmp}/papers.db")


def _add(store, title: str, doi: str = "") -> int:
    from hfpapers.paper_store import PaperRecord

    sf_id = store.upsert_paper(PaperRecord(title=title, source="test"))
    if doi:
        store.add_identifier(sf_id, "doi", doi, source="test")
    return sf_id


class TestIdentityGuard:
    """An identifier-less arrival must not re-file a work the store already has."""

    def test_no_identifier_arrival_reuses_the_existing_record(self, monkeypatch):
        import hfpapers.paper_store as ps

        with tempfile.TemporaryDirectory() as tmpdir:
            ps._store_instance = PaperStore(db_path=f"{tmpdir}/papers.db")
            try:
                existing = _add(ps._store_instance, TITLE, "10.1016/s0375-9601(96)00765-7")
                sf_id, created = ps.ensure_paper("", title=TITLE, source="orcid-no-doi-pass")
                assert (sf_id, created) == (existing, False)
                assert ps._store_instance._conn().execute(
                    "SELECT COUNT(*) FROM papers").fetchone()[0] == 1
                kinds = [r[0] for r in ps._store_instance._conn().execute("SELECT kind FROM store_events")]
                assert "identity_reused" in kinds  # the reuse is recorded, not silent
            finally:
                ps._store_instance = None

    def test_a_caller_with_its_own_identifier_is_unaffected(self, monkeypatch):
        """Only the identifier-less case is guarded: a second DOI is the version-pair case."""
        import hfpapers.paper_store as ps

        with tempfile.TemporaryDirectory() as tmpdir:
            ps._store_instance = PaperStore(db_path=f"{tmpdir}/papers.db")
            try:
                _add(ps._store_instance, TITLE, "10.1016/s0375-9601(96)00765-7")
                _sf_id, created = ps.ensure_paper(
                    "", doi="10.1000/other-registry-entry", title=TITLE, verify_doi=False
                )
                assert created is True
                assert ps._store_instance._conn().execute(
                    "SELECT COUNT(*) FROM papers").fetchone()[0] == 2
            finally:
                ps._store_instance = None

    def test_find_by_identity_matches_the_grouping_key(self, store):
        sf = _add(store, "Energetic-Particle-Induced Geodesic Acoustic Mode")
        assert store.find_by_identity("energetic particle induced geodesic acoustic mode") == [sf]
        assert store.find_by_identity("nothing like it") == []


class TestDedupApply:
    """`store dedup --apply` deletes records, so the merge path gets an end-to-end run.

    Offline this is the pre-0.19.12 behaviour (identifier kinds decide), which is exactly the
    guarantee worth pinning: the new evidence only ever adds verdicts, it does not change this one.
    """

    def test_one_work_filed_twice_is_merged(self):
        from typer.testing import CliRunner

        import hfpapers.paper_store as ps
        from hfpapers.cli import app
        from hfpapers.paper_store import PaperRecord, get_store

        ps._store_instance = None
        try:
            store = get_store()
            first = store.upsert_paper(PaperRecord(title="Optimizing omnigenity", source="batch"))
            store.add_identifier(first, "arxiv", "2502.09350", source="batch")
            second = store.upsert_paper(PaperRecord(title="Optimizing omnigenity", source="no-doi-pass"))
            store.add_identifier(second, "doi", "10.1000/registry", source="no-doi-pass")

            result = CliRunner().invoke(app, ["store", "dedup", "--apply"])
            assert result.exit_code == 0, result.output
            conn = store._conn()
            assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 1
            survivor = conn.execute("SELECT sf_id FROM papers").fetchone()[0]
            kinds = {r[0] for r in conn.execute(
                "SELECT id_type FROM identifiers WHERE sf_id=?", (survivor,))}
            assert kinds == {"arxiv", "doi"}  # both identifiers live on the survivor
        finally:
            ps._store_instance = None
