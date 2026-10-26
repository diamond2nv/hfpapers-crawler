#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression test: a Crossref *title search* must not hand back a stranger.

Live bug (2026-10-05): importing arXiv 2607.27201 ("Mental World Modeling") wrote the wrong DOI
``10.1007/978-1-4939-6616-5_3`` ("Science of Mental Modeling", a 2017 Springer book chapter) and
stamped ``year=2017 · venue='Mental Modeling Approach'`` onto the record.  Crossref's ``/works?query=``
is a fuzzy search — it matched on the shared words "Mental"/"Modeling" — and the old 0.3 similarity
floor returned the chapter anyway; the ``sim + 0.2`` confidence bonus (0.587) then sat just under the
store's 0.6 gate, so the same class slipped through whenever the bonus cleared it (a live record still
carries ``10.1109/wacv51458.2022.00025`` — "SSCAP…" on a "ConsensusTAS…" paper at 0.404 → 0.604).

The candidate floor is now ``CrossrefClient.MIN_TITLE_SIMILARITY`` (0.5), the same bar the supplied-DOI
path uses.  The hit lists below are the *real* Crossref responses captured for the two queries, so the
test exercises the actual similarity arithmetic, not a hand-tuned number.
"""
import os
import tempfile

from hfpapers.paper_store import CrossrefClient, PaperStore

#: Real Crossref response for query="Mental World Modeling" (captured 2026-10-05, api.crossref.org).
_MWM_HITS = [
    {"doi": "10.31234/osf.io/z6swk_v1",
     "title": "Cognitive Modeling of Real-World Behavior for Understanding Mental Health",
     "venue": "", "year": 2025},
    {"doi": "10.2139/ssrn.5957258",
     "title": "Modeling the Mental World for Embodied AI: A Comprehensive Review",
     "venue": "", "year": 2026},
    {"doi": "10.20944/preprints202512.2200.v1",
     "title": "Modeling the Mental World for Embodied AI: A Comprehensive Review",
     "venue": "", "year": 2025},
    {"doi": "10.1007/978-1-4939-6616-5_3",
     "title": "Science of Mental Modeling",
     "venue": "Mental Modeling Approach", "year": 2017},
    {"doi": "10.3109/01612849509009395",
     "title": "Modeling the Client's World Through Brief Solution-Focused Therapy",
     "venue": "Issues in Mental Health Nursing", "year": 1995},
]

#: Real Crossref response for query="Efficient Large Language Models: A Survey" — the correct work is
#: the top hit (its Crossref title is the truncated form), a genuine match the floor must keep.
_EFFICIENT_HITS = [
    {"doi": "10.1201/9781003650065-9", "title": "Efficient Large Language Models",
     "venue": "Large Language Models", "year": 2024},
]


class TestCrossrefTitleGate:
    """`CrossrefClient.cross_verify` refuses a hit whose title similarity is below the floor."""

    def _client_with(self, monkeypatch, hits):
        cr = CrossrefClient()
        monkeypatch.setattr(cr, "title_to_doi", lambda _title: hits)
        return cr

    def test_stranger_title_is_refused(self, monkeypatch):
        """The polluted instance: no candidate is returned, so nothing downstream can attach it."""
        cr = self._client_with(monkeypatch, _MWM_HITS)
        assert cr.cross_verify("2607.27201", "Mental World Modeling") is None

    def test_genuine_title_match_is_still_returned(self, monkeypatch):
        """The positive control: a real title match (sim ~0.75) is unaffected by the floor."""
        cr = self._client_with(monkeypatch, _EFFICIENT_HITS)
        result = cr.cross_verify("2312.03863", "Efficient Large Language Models: A Survey")
        assert result is not None
        assert result["doi"] == "10.1201/9781003650065-9"

    def test_floor_boundary(self, monkeypatch):
        """A hit on the kept side of the floor is returned; one below it is refused."""
        from hfpapers.search_queue import _title_similarity

        query = "Alpha Beta Gamma Delta"
        kept_title = "Alpha Beta Gamma Delta Epsilon Zeta"       # sim 0.645
        refused_title = "Unrelated Topic About Something Else Entirely"  # sim 0.000
        assert _title_similarity(query, kept_title) >= CrossrefClient.MIN_TITLE_SIMILARITY
        assert _title_similarity(query, refused_title) < CrossrefClient.MIN_TITLE_SIMILARITY

        kept = CrossrefClient()
        monkeypatch.setattr(kept, "title_to_doi",
                            lambda _t: [{"doi": "10.0/kept", "title": kept_title,
                                         "venue": "", "year": 2026}])
        refused = CrossrefClient()
        monkeypatch.setattr(refused, "title_to_doi",
                            lambda _t: [{"doi": "10.0/refused", "title": refused_title,
                                         "venue": "", "year": 2026}])
        assert kept.cross_verify("0000.00000", query)["doi"] == "10.0/kept"
        assert refused.cross_verify("0000.00000", query) is None


class TestEnsurePaperCrossrefDoesNotPollute:
    """End-to-end: `ensure_paper` writes neither the stranger DOI nor its venue/year."""

    def test_import_of_mwm_leaves_record_clean(self, monkeypatch):
        import hfpapers.paper_store as ps

        with tempfile.TemporaryDirectory() as tmpdir:
            store = PaperStore(db_path=os.path.join(tmpdir, "papers.db"))
            monkeypatch.setattr(ps, "get_store", lambda: store)
            cr = CrossrefClient()
            monkeypatch.setattr(cr, "title_to_doi", lambda _title: _MWM_HITS)
            monkeypatch.setattr(ps, "get_crossref", lambda: cr)

            sf, _ = ps.ensure_paper("2607.27201", title="Mental World Modeling", source="import")
            paper = store.get_paper_by_id(sf)
            dois = [i.id_value for i in store.get_identifiers(sf) if i.id_type == "doi"]

            assert dois == []  # the 2017 Springer chapter DOI was never attached
            assert paper.venue != "Mental Modeling Approach"
            assert paper.year != 2017

    def test_correct_match_is_attached_with_its_venue(self, monkeypatch):
        import hfpapers.paper_store as ps

        with tempfile.TemporaryDirectory() as tmpdir:
            store = PaperStore(db_path=os.path.join(tmpdir, "papers.db"))
            monkeypatch.setattr(ps, "get_store", lambda: store)
            cr = CrossrefClient()
            monkeypatch.setattr(cr, "title_to_doi", lambda _title: _EFFICIENT_HITS)
            monkeypatch.setattr(ps, "get_crossref", lambda: cr)

            sf, _ = ps.ensure_paper(
                "2312.03863", title="Efficient Large Language Models: A Survey", source="import"
            )
            dois = [i.id_value for i in store.get_identifiers(sf) if i.id_type == "doi"]
            assert dois == ["10.1201/9781003650065-9"]
            assert store.get_paper_by_id(sf).venue == "Large Language Models"
