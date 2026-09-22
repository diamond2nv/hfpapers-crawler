#!/usr/bin/env python3
"""v0.19.7 回归测试：标识符置信度写入闸门（add_identifier 拦截 + ensure_paper 的 Crossref 路径不再污染 venue/year）"""
import json
import os
import tempfile

from hfpapers.invariants import ACCEPTED_UNVERIFIED_TAG, LOW_CONFIDENCE_THRESHOLD
from hfpapers.paper_store import PaperRecord, PaperStore


class TestIdentifierConfidenceGate:
    """The gate the data-integrity pass asked for: no low-confidence identifier lands silently.

    Three live occurrences motivated this (2026-09-19..21): a 2001 Neuroreport chapter DOI attached
    to an ICLR 2026 paper, a 2013 Nature news DOI on a long-context paper, and a 1990 psychology
    chapter DOI on a 2026 preprint — all `store ensure` auto-attach, confidences 0.51-0.58.
    """

    def _store(self, tmpdir: str) -> PaperStore:
        return PaperStore(db_path=os.path.join(tmpdir, "papers.db"))

    def test_low_confidence_is_refused_and_logged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="T", year=2026, venue="arXiv"))
            assert store.add_identifier(sf, "doi", "10.1000/wrong", source="crossref",
                                        confidence=LOW_CONFIDENCE_THRESHOLD - 0.1) is False
            # nothing written
            assert store.get_identifiers(sf) == []
            # refusal is recorded, with the evidence needed to act
            ev = next(e for e in store.events(sf_id=sf) if e["kind"] == "identifier_rejected")
            detail = json.loads(ev["detail"])
            assert detail["id_value"] == "10.1000/wrong"
            assert detail["confidence"] < LOW_CONFIDENCE_THRESHOLD

    def test_threshold_boundary_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="T", year=2026, venue="arXiv"))
            assert store.add_identifier(sf, "doi", "10.1000/edge", source="crossref",
                                        confidence=LOW_CONFIDENCE_THRESHOLD) is True
            assert [i.id_value for i in store.get_identifiers(sf)] == ["10.1000/edge"]

    def test_explicit_acceptance_by_argument(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="T", year=2026, venue="arXiv"))
            assert store.add_identifier(sf, "doi", "10.1000/checked", source="crossref",
                                        confidence=0.2, accept_unverified=True) is True
            assert [i.id_value for i in store.get_identifiers(sf)] == ["10.1000/checked"]

    def test_explicit_acceptance_by_record_tag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="T", year=2026, venue="arXiv"))
            store.add_identifier(sf, "tag", ACCEPTED_UNVERIFIED_TAG, source="test")
            assert store.add_identifier(sf, "doi", "10.1000/tagged", source="crossref",
                                        confidence=0.2) is True
            values = {i.id_value for i in store.get_identifiers(sf)}
            assert "10.1000/tagged" in values

    def test_guarded_write_leaves_no_low_confidence_invariant(self):
        from hfpapers.invariants import check_store

        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            sf = store.upsert_paper(PaperRecord(title="T", year=2026, venue="arXiv"))
            store.add_identifier(sf, "arxiv", "2609.02702", source="test")
            store.add_identifier(sf, "doi", "10.1000/wrong", source="crossref", confidence=0.52)
            checks = check_store(store).by_check()
            assert "identifier.low_confidence" not in checks
            assert checks.get("identifier.unknown_type") is None


class TestEnsurePaperCrossrefGate:
    """`ensure_paper` must not let a sub-threshold Crossref hit attach a DOI *or* rewrite venue/year."""

    def _store(self, tmpdir: str) -> PaperStore:
        return PaperStore(db_path=os.path.join(tmpdir, "papers.db"))

    def test_subthreshold_crossref_hit_does_not_attach_or_pollute(self, monkeypatch):
        import hfpapers.paper_store as ps

        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            monkeypatch.setattr(ps, "get_store", lambda: store)

            class FakeCR:
                def cross_verify(self, arxiv_id, title):
                    return {"doi": "10.1097/00001756-200107030-00003", "confidence": 0.52,
                            "venue": "Advances in Psychology", "year": 1990}

            monkeypatch.setattr(ps, "get_crossref", lambda: FakeCR())
            sf, _is_new = ps.ensure_paper("2609.02702",
                                          title="Trace as State: Reasoning Traces as Conditional States",
                                          source="test")
            paper = store.get_paper_by_id(sf)
            ids = store.get_identifiers(sf) or []
            # DOI refused …
            assert not [i for i in ids if i.id_type == "doi"]
            # … and the record keeps its own venue/year (the second half of the live bug)
            assert paper.venue != "Advances in Psychology"
            assert paper.year != 1990
            assert any(e["kind"] == "identifier_rejected" for e in store.events(sf_id=sf))

    def test_confident_crossref_hit_still_attaches(self, monkeypatch):
        import hfpapers.paper_store as ps

        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            monkeypatch.setattr(ps, "get_store", lambda: store)

            class FakeCR:
                def cross_verify(self, arxiv_id, title):
                    return {"doi": "10.1234/right", "confidence": 0.95,
                            "venue": "Nature Machine Intelligence", "year": 2026}

            monkeypatch.setattr(ps, "get_crossref", lambda: FakeCR())
            sf, _ = ps.ensure_paper("2609.02702", title="Trace as State", source="test")
            assert [i.id_value for i in store.get_identifiers(sf) if i.id_type == "doi"] == ["10.1234/right"]
            assert store.get_paper_by_id(sf).venue == "Nature Machine Intelligence"


class TestCrossRefAttachVerdicts:
    """`crossref_attach` is the store's single decision point — its verdicts must be distinct.

    The verdict is what lets a caller act: "refused" (nothing written, nothing rewritten) is a
    different outcome from "none" (no candidate at all), and a caller that cannot tell them apart
    reports a refusal as a miss.
    """

    def _store(self, tmpdir: str) -> PaperStore:
        return PaperStore(db_path=os.path.join(tmpdir, "papers.db"))

    def _candidate(self, monkeypatch, payload: dict | None) -> None:
        import hfpapers.paper_store as ps

        class FakeCR:
            def cross_verify(self, arxiv_id, title):
                return payload

        monkeypatch.setattr(ps, "get_crossref", lambda: FakeCR())

    SUBTHRESHOLD = {"doi": "10.1097/00001756-200107030-00003", "confidence": 0.52,
                    "venue": "Advances in Psychology", "year": 1990}

    def test_refused_verdict_leaves_identifier_and_metadata_alone(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            self._candidate(monkeypatch, self.SUBTHRESHOLD)
            sf = store.upsert_paper(PaperRecord(title="Trace as State", year=2026, venue="arXiv"))
            assert store.crossref_attach(sf, "2609.02702", "Trace as State") == "refused"
            assert not [i for i in store.get_identifiers(sf) if i.id_type == "doi"]
            paper = store.get_paper_by_id(sf)
            assert (paper.venue, paper.year) == ("arXiv", 2026)

    def test_no_candidate_verdict_is_none(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            self._candidate(monkeypatch, None)
            sf = store.upsert_paper(PaperRecord(title="T", year=2026))
            assert store.crossref_attach(sf, "2609.02702", "T") == "none"
            assert store.events(sf_id=sf, kind="identifier_rejected") == []

    def test_record_tag_turns_the_same_candidate_into_an_attach(self, monkeypatch):
        """The tag route works through the Crossref path, not only through a direct call."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            self._candidate(monkeypatch, self.SUBTHRESHOLD)
            sf = store.upsert_paper(PaperRecord(title="Trace as State", year=2026))
            store.add_identifier(sf, "tag", ACCEPTED_UNVERIFIED_TAG, source="test")
            assert store.crossref_attach(sf, "2609.02702", "Trace as State") == "attached"
            assert [i.id_value for i in store.get_identifiers(sf) if i.id_type == "doi"] == [
                self.SUBTHRESHOLD["doi"]
            ]
            accepted = store.events(sf_id=sf, kind="identifier_accepted_unverified")
            assert accepted and ACCEPTED_UNVERIFIED_TAG in accepted[0]["detail"]

    def test_accept_unverified_argument_turns_it_into_an_attach(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            self._candidate(monkeypatch, self.SUBTHRESHOLD)
            sf = store.upsert_paper(PaperRecord(title="T", year=2026))
            assert store.crossref_attach(sf, "2609.02702", "T", accept_unverified=True) == "attached"
            assert [i.id_value for i in store.get_identifiers(sf) if i.id_type == "doi"] == [
                self.SUBTHRESHOLD["doi"]
            ]

    def test_acceptance_route_through_ensure_paper(self, monkeypatch):
        import hfpapers.paper_store as ps

        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            monkeypatch.setattr(ps, "get_store", lambda: store)
            self._candidate(monkeypatch, self.SUBTHRESHOLD)
            sf, _ = ps.ensure_paper("2609.02702", title="Trace as State", source="test",
                                    accept_unverified=True)
            assert [i.id_value for i in store.get_identifiers(sf) if i.id_type == "doi"] == [
                self.SUBTHRESHOLD["doi"]
            ]


class TestBatchVerifyHonoursRefusal:
    """`hfpclawer store cron-verify` is the scheduled twin of `ensure_paper`'s auto-attach.

    It ignored `add_identifier`'s return value, so a refused candidate was still counted as found
    and its `venue`/`year` were still stamped onto the record — the refusal only half-worked on the
    one path most likely to run unattended.
    """

    def test_refused_candidate_is_not_counted_and_does_not_touch_metadata(self, monkeypatch):
        from hfpclawer.audit import cron_verify

        with tempfile.TemporaryDirectory() as tmpdir:
            store = PaperStore(db_path=os.path.join(tmpdir, "papers.db"))
            sf = store.upsert_paper(PaperRecord(title="Trace as State", year=2026, venue="arXiv",
                                                source="cron:test"))
            store.add_identifier(sf, "arxiv", "2609.02702", source="cron:test")

            class FakeCR:
                def cross_verify(self, arxiv_id, title):
                    return {"doi": "10.1097/00001756-200107030-00003", "confidence": 0.52,
                            "venue": "Advances in Psychology", "year": 1990}

            monkeypatch.setattr(cron_verify, "_check_retraction", lambda *a, **k: None)
            stats = cron_verify.batch_verify(store, FakeCR(), rate=0)

            assert stats.doi_rejected == 1
            assert (stats.doi_found, stats.verified_new) == (0, 0)
            assert not [i for i in store.get_identifiers(sf) if i.id_type == "doi"]
            paper = store.get_paper_by_id(sf)
            assert (paper.venue, paper.year) == ("arXiv", 2026)
