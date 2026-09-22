#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# test_invariants.py
"""Store invariants, the row-level event log, and `store dedup`.

These tests are written from the failures they exist to catch. Each defect class below was found in
the live store on 2026-09-19 (`docs/AUDIT_CRITIQUE.md`); the tests assert the gate *would have said
so*, and that a clean store stays quiet — a gate that is always red is not a gate.
"""

import json
import os
import sqlite3
import tempfile

import pytest

from hfpapers.invariants import (
    ACCEPTED_UNVERIFIED_TAG,
    LOW_CONFIDENCE_THRESHOLD,
    Finding,
    identity_key,
    normalise_title,
)
from hfpapers.paper_store import PaperRecord, PaperStore


def _store(tmpdir: str) -> PaperStore:
    return PaperStore(db_path=os.path.join(tmpdir, "papers.db"))


def _checks(report) -> dict[str, int]:
    return report.by_check()


@pytest.fixture
def cli_store():
    """The store the CLI will actually open.

    ``get_store()`` caches a module-level instance resolved from config, while the ``paper_store``
    fixture builds its own ``mkstemp`` database — so a CLI test that seeds the fixture would assert
    against a store the CLI never opens. This fixture clears the cache so both sides agree, and
    ``conftest.test_env`` has already pointed the data directory at a temp dir for the test.
    """
    import hfpapers.paper_store as ps

    with tempfile.TemporaryDirectory() as tmpdir:
        store = PaperStore(db_path=os.path.join(tmpdir, "papers.db"))
        ps._store_instance = store  # the CLI reads this global, so both sides are the same DB
        try:
            yield store
        finally:
            ps._store_instance = None


class TestIdentityKey:
    def test_title_is_the_grouping_key(self):
        # Two copies of one paper cannot share an identifier (UNIQUE(id_type,id_value)), so the
        # title is the only field they have in common — keying on the DOI would find zero duplicates.
        a = identity_key("Same Work", 2024, [("doi", "10.1000/x")])
        b = identity_key("Same Work", 2024, [("arxiv", "2401.00001")])
        assert a == b == "title:samework"  # year is not part of the key

    def test_identifier_is_the_fallback_when_there_is_no_title(self):
        assert identity_key("", 0, [("doi", "10.1/x")]) == "doi:10.1/x"
        assert identity_key("", 0, [("arxiv", "2401.00001")]) == "arxiv:2401.00001"

    def test_empty_title_without_identifier_has_no_key(self):
        assert identity_key("", 0, []) == ""

    def test_normalise_title_folds_punctuation_and_case(self):
        assert normalise_title("DeepONet: A Library!") == normalise_title("deeponet a library")


class TestOfflineChecks:
    def test_clean_store_reports_nothing(self):
        from hfpapers.invariants import check_store

        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="A Good Paper", year=2024, venue="Nature"))
            store.add_identifier(sf, "doi", "10.1000/ok", source="test")
            report = check_store(store)
            assert report.errors == []
            assert report.warnings == []
            assert report.coverage["year_coverage"] == 1.0

    def test_year_out_of_domain_is_an_error(self):
        from hfpapers.invariants import check_store

        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="T", year=2206))
            store.add_identifier(sf, "arxiv", "2206.14588", source="test")
            report = check_store(store)
            assert _checks(report)["year.out_of_domain"] == 1
            assert "2206" in report.errors[0].detail

    def test_year_unknown_is_not_an_error_but_is_counted(self):
        from hfpapers.invariants import check_store

        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="T", year=0, venue="arXiv"))
            store.add_identifier(sf, "arxiv", "2401.00001", source="test")
            report = check_store(store)
            assert report.errors == []
            assert report.coverage["year_coverage"] == 0.0

    def test_title_equal_to_identifier(self):
        from hfpapers.invariants import check_store

        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="10.1090/noti1300", year=2015))
            store.add_identifier(sf, "doi", "10.1090/noti1300", source="test")
            report = check_store(store)
            assert _checks(report)["title.is_identifier"] == 1

    def test_citation_string_title_is_a_warning(self):
        from hfpapers.invariants import check_store

        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="Lu, L., Meng, X. & Karniadakis, G. E. DeepXDE", year=2021))
            store.add_identifier(sf, "doi", "10.1137/19M1274067", source="test")
            report = check_store(store)
            assert _checks(report)["title.is_citation"] == 1
            assert report.errors == []  # a warning: the DOI itself is fine

    def test_low_confidence_doi_is_a_warning_unless_accepted(self):
        from hfpapers.invariants import check_store

        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="T", year=2024, venue="Nature"))
            # Seeded with SQL on purpose: since v0.19.7 the write path refuses this row, and the
            # invariant's job is the rows the write path cannot see — a restore, a snapshot import,
            # or a database written by an older version.  Exercising it through `add_identifier`
            # would only test the gate, and would stop testing the check.
            with store._conn() as conn:
                conn.execute(
                    "INSERT INTO identifiers (sf_id, id_type, id_value, source, confidence) "
                    "VALUES (?,?,?,?,?)",
                    (sf, "doi", "10.1000/risky", "reconcile", LOW_CONFIDENCE_THRESHOLD - 0.1),
                )
            assert _checks(check_store(store))["identifier.low_confidence"] == 1
            store.add_identifier(sf, "tag", ACCEPTED_UNVERIFIED_TAG, source="test")
            assert _checks(check_store(store)).get("identifier.low_confidence", 0) == 0

    def test_non_paper_doi_shapes_are_flagged(self):
        from hfpapers.invariants import check_store

        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="T", year=2024, venue="IEEE TNNLS"))
            store.add_identifier(sf, "doi", "10.1109/tnnls.2025.3552223/mm1", source="reconcile")
            report = check_store(store)
            found = [f for f in report.findings if f.check == "doi.non_paper_shape"]
            assert len(found) == 1
            assert found[0].evidence["kind"] == "supplementary-material"

    def test_record_without_identifier_is_a_warning(self):
        from hfpapers.invariants import check_store

        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            store.upsert_paper(PaperRecord(title="Orphan", year=2024))
            assert _checks(check_store(store))["record.no_identifier"] == 1

    def test_duplicate_identity_is_an_error_for_every_member(self):
        from hfpapers.invariants import check_store

        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            a = store.upsert_paper(PaperRecord(title="Same Paper", year=2024, venue="Nature"))
            b = store.upsert_paper(PaperRecord(title="Same Paper", year=2024, venue=""))
            store.add_identifier(a, "doi", "10.1000/dup", source="test")
            store.add_identifier(b, "arxiv", "2401.00009", source="test")  # complementary id
            report = check_store(store)
            assert _checks(report)["record.duplicate_identity"] == 2

    def test_same_title_different_years_is_a_warning_not_a_duplicate(self):
        from hfpapers.invariants import check_store

        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            a = store.upsert_paper(PaperRecord(title="Collision", year=2019))
            b = store.upsert_paper(PaperRecord(title="Collision", year=2023))
            store.add_identifier(a, "doi", "10.1000/a", source="test")
            store.add_identifier(b, "doi", "10.1000/b", source="test")
            report = check_store(store)
            assert _checks(report)["record.title_collision"] == 2
            assert "record.duplicate_identity" not in _checks(report)

    def test_unknown_identifier_and_item_type_are_errors(self):
        from hfpapers.invariants import check_store

        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="T", year=2024, venue="Nature"))
            store.add_identifier(sf, "journl", "Nature", source="test")  # typo'd kind
            with sqlite3.connect(store.db_path) as conn:
                conn.execute("UPDATE papers SET item_type='misc' WHERE sf_id=?", (sf,))
            checks = _checks(check_store(store))
            assert checks["identifier.unknown_type"] == 1
            assert checks["item_type.unknown"] == 1

    def test_report_serialises(self):
        from hfpapers.invariants import check_store, format_report, report_json

        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            store.upsert_paper(PaperRecord(title="", year=3000))
            report = check_store(store)
            payload = json.loads(report_json(report))
            assert payload["ok"] is False and payload["errors"] >= 1
            assert "error(s)" in format_report(report)
            assert all(isinstance(f, Finding) for f in report.findings)


class TestEventLog:
    def test_identifier_attach_records_method_and_actor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="T", year=2024))
            store.add_identifier(sf, "doi", "10.1/x", source="reconcile", confidence=0.9,
                                 actor="agent", method="crossref title match 0.90")
            events = store.events(sf_id=sf)
            assert events and events[0]["kind"] == "identifier_add"
            detail = json.loads(events[0]["detail"])
            assert detail["method"] == "crossref title match 0.90"
            assert events[0]["actor"] == "agent"

    def test_remove_identifier_requires_a_selector(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="T", year=2024))
            store.add_identifier(sf, "doi", "10.1/x", source="test")
            with pytest.raises(ValueError):
                store.remove_identifier(sf)  # refusing to match everything
            assert store.remove_identifier(sf, id_type="doi", actor="agent", reason="wrong paper") == 1
            kinds = [e["kind"] for e in store.events(sf_id=sf)]
            assert "identifier_remove" in kinds

    def test_remove_paper_snapshots_the_row_inside_the_event(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="Doomed", year=2024))
            store.add_identifier(sf, "arxiv", "2401.00001", source="test")
            assert store.remove_paper(sf, actor="agent", reason="duplicate") is True
            assert store.get_paper_by_id(sf) is None
            ev = next(e for e in store.events() if e["kind"] == "record_remove")
            detail = json.loads(ev["detail"])
            assert detail["record"]["title"] == "Doomed"
            assert detail["identifiers"][0]["id_value"] == "2401.00001"

    def test_item_type_change_is_recorded_with_before_and_after(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="T", year=2024, venue="Nature"))
            store.set_item_type(sf, "preprint", src="derived")
            store.set_item_type(sf, "journalArticle", src="manual")
            ev = next(e for e in store.events(sf_id=sf) if e["kind"] == "item_type_set")
            detail = json.loads(ev["detail"])
            assert detail["after"] == "journalArticle" and detail["after_src"] == "manual"

    def test_snapshot_writes_a_file_and_logs_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="T", year=2024))
            store.add_identifier(sf, "doi", "10.1/x", source="test")
            path = store.snapshot(dest=tmpdir, reason="test")
            payload = json.loads(open(path, encoding="utf-8").read())
            assert payload["papers"] and payload["identifiers"]
            assert any(e["kind"] == "snapshot" for e in store.events())


class TestDedupCommand:
    def _run(self, args):
        from typer.testing import CliRunner

        from hfpapers.cli import app

        return CliRunner().invoke(app, ["store", *args])

    def _seed_duplicate(self, store: PaperStore) -> tuple[int, int]:
        keeper = store.upsert_paper(PaperRecord(title="Same Work", year=2024, venue="Nature"))
        store.add_identifier(keeper, "doi", "10.1000/same", source="test")
        loser = store.upsert_paper(PaperRecord(title="Same Work", year=2024))
        store.add_identifier(loser, "arxiv", "2401.00001", source="test")
        return keeper, loser

    def test_dry_run_reports_without_touching(self, cli_store):
        keeper, loser = self._seed_duplicate(cli_store)
        res = self._run(["dedup"])
        assert res.exit_code == 0, res.stdout
        assert cli_store.get_paper_by_id(loser) is not None  # dry run: nothing merged
        assert "dry run" in res.stdout

    def test_apply_moves_identifiers_then_drops_the_loser(self, cli_store):
        keeper, loser = self._seed_duplicate(cli_store)
        res = self._run(["dedup", "--apply"])
        assert res.exit_code == 0, res.stdout
        assert cli_store.get_paper_by_id(loser) is None
        values = {i.id_value for i in cli_store.get_identifiers(keeper) or []}
        assert {"10.1000/same", "2401.00001"} <= values  # the regression that motivated this
        assert [e["kind"] for e in cli_store.events(kind="record_remove")] == ["record_remove"]

    def test_mismatched_titles_are_skipped(self, cli_store):
        a = cli_store.upsert_paper(PaperRecord(title="Paper One", year=2024, venue="Nature"))
        cli_store.add_identifier(a, "doi", "10.1000/one", source="test")
        b = cli_store.upsert_paper(PaperRecord(title="Paper Two", year=2024))
        cli_store.add_identifier(b, "arxiv", "2401.00002", source="test")
        res = self._run(["dedup", "--apply"])
        assert res.exit_code == 0
        assert cli_store.get_paper_by_id(b) is not None  # different titles never merged


class TestCliInvariants:
    def test_strict_exits_nonzero_on_error(self, cli_store):
        from typer.testing import CliRunner

        from hfpapers.cli import app

        cli_store.upsert_paper(PaperRecord(title="", year=2024))  # empty title → error
        assert CliRunner().invoke(app, ["store", "invariants", "--strict"]).exit_code == 1
        plain = CliRunner().invoke(app, ["store", "invariants"])
        assert plain.exit_code == 0 and "title.empty" in plain.stdout

    def test_json_output_is_machine_readable(self, cli_store):
        from typer.testing import CliRunner

        from hfpapers.cli import app

        cli_store.upsert_paper(PaperRecord(title="T", year=2024, venue="Nature"))
        res = CliRunner().invoke(app, ["store", "invariants", "--json"])
        assert res.exit_code == 0
        start = res.stdout.index("{")
        payload = json.loads(res.stdout[start:])
        assert "findings" in payload and payload["coverage"]["papers"] == 1

class TestBaselineRatchet:
    def test_regression_against_baseline_is_detected(self):
        from hfpapers.invariants import InvariantReport, baseline_diff

        rep = InvariantReport()
        rep.findings = [Finding("title.empty", "error", "1", "x"), Finding("title.empty", "error", "2", "x")]
        regressions, improvements = baseline_diff(rep, {"title.empty": 1})
        assert regressions == ["title.empty: 1 → 2"]

    def test_improvement_is_reported_and_does_not_fail(self):
        from hfpapers.invariants import InvariantReport, baseline_diff

        rep = InvariantReport()
        regressions, improvements = baseline_diff(rep, {"title.empty": 3})
        assert regressions == []
        assert improvements == ["title.empty: 3 → 0"]

    def test_strict_uses_the_recorded_baseline(self, cli_store):
        from typer.testing import CliRunner

        from hfpapers.cli import app

        runner = CliRunner()
        cli_store.upsert_paper(PaperRecord(title="", year=2024))  # one error
        assert runner.invoke(app, ["store", "invariants", "--update-baseline"]).exit_code == 0
        assert runner.invoke(app, ["store", "invariants", "--strict"]).exit_code == 0  # at baseline
        cli_store.upsert_paper(PaperRecord(title="", year=2024))  # second error → regression
        res = runner.invoke(app, ["store", "invariants", "--strict"])
        assert res.exit_code == 1 and "regression" in res.stdout


class TestDedupSafetyRule:
    def test_same_work_different_artefacts_is_never_auto_merged(self, cli_store):
        """A journal paper and its OSTI report share a title but are legitimately two records."""
        from typer.testing import CliRunner

        from hfpapers.cli import app

        a = cli_store.upsert_paper(PaperRecord(title="One Work", year=1996, venue="Physics Letters A"))
        cli_store.add_identifier(a, "doi", "10.1016/s0375-9601(96)00765-7", source="orcid")
        b = cli_store.upsert_paper(PaperRecord(title="One Work", year=1996, venue="OSTI Technical Report"))
        cli_store.add_identifier(b, "doi", "10.2172/839535", source="orcid")
        res = CliRunner().invoke(app, ["store", "dedup", "--apply"])
        assert res.exit_code == 0
        assert cli_store.get_paper_by_id(b) is not None
        assert "manual" in res.stdout

