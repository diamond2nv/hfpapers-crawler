"""Gates for the reusable round runner (`scripts/cron_round.py`).

Why this file exists
--------------------
The round runner replaces per-round one-shot scripts, and the defects it guards against were all
paid for in the store on 2026-10-10:

* an id-form split (`2610.06986` vs `2610.06986v1`) that made a dedup probe miss the paper it was
  meant to find, leaving a stray row titled `x` beside the real record for `2609.09203`;
* a private arXiv client that disabled TLS verification for no reason;
* "which candidates are new" recomputed by hand every round.

The pure logic is covered here so a regression in any of those shows up as a red test rather than as
another silent duplicate three rounds later. Everything runs offline: the store is a fake and the
network path is not touched.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "cron_round.py"
    if not path.is_file():
        pytest.skip("scripts/cron_round.py is not present in this checkout")
    spec = importlib.util.spec_from_file_location("cron_round", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cron_round = _load_module()


# ------------------------------------------------------------------------------------------- fakes


class FakeRecord:
    """Stand-in for a stored paper row; `year=0` is the store's "not filled" value."""

    def __init__(self, year: int = 0) -> None:
        self.year = year


class FakeStore:
    """Minimal stand-in exposing only the public methods the runner is allowed to use."""

    def __init__(self, arxiv_values: list[str] | None = None, per_paper: bool = True) -> None:
        self._values = list(arxiv_values or [])
        self._per_paper = per_paper
        self.years: dict[int, int] = {}
        self.updates: list[tuple[int, dict]] = []

    def get_paper_by_identifier(self, id_type: str, id_value: str):
        if id_type != "arxiv" or id_value not in self._values:
            return None
        return SimpleNamespace(sf_id=abs(hash(id_value)) % 10**9)

    def get_paper_by_id(self, sf_id: int):
        return FakeRecord(self.years.get(sf_id, 0))

    def update_paper(self, sf_id: int, **kwargs) -> bool:
        self.updates.append((sf_id, kwargs))
        if "year" in kwargs:
            self.years[sf_id] = kwargs["year"]
        return True

    def get_all_papers(self):
        return [SimpleNamespace(sf_id=index) for index, _ in enumerate(self._values)]

    def get_identifiers(self, sf_id: int):
        return [SimpleNamespace(id_type="arxiv", id_value=self._values[sf_id])]


# ---------------------------------------------------------------------------------- id normalisation


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2610.06986", "2610.06986"),
        ("2610.06986v1", "2610.06986"),
        ("2610.06986v12", "2610.06986"),
        ("  2609.37603v3  ", "2609.37603"),
        ("2609.1234", "2609.1234"),
    ],
)
def test_normalize_accepts_bare_and_versioned_forms(raw: str, expected: str) -> None:
    assert cron_round.normalize_arxiv_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", "hello", "10.1017/s0022377823000880", "2610", "2610.06v1"])
def test_normalize_rejects_non_arxiv_values(raw: str) -> None:
    """A DOI-shaped or truncated value must raise: it must not enter the store as a new paper.

    This is the gate on the six `10.*` values currently mislabelled as arXiv ids in the store.
    """
    with pytest.raises(ValueError):
        cron_round.normalize_arxiv_id(raw)


def test_versioned_and_bare_forms_compare_equal() -> None:
    """The exact defect of the one-shot scripts: these two strings are the same paper."""
    assert cron_round.normalize_arxiv_id("2609.09203") == cron_round.normalize_arxiv_id("2609.09203v1")


# ------------------------------------------------------------------------------------ axis url build


def test_build_axis_url_keeps_space_form_operators_literal() -> None:
    """The measured trap: `urlencode`-ing the whole query rewrites the query the API then ignores.

    Queries as written in practice are space-separated (`A AND B`), so the spaces become `%20` --
    what must NOT happen is `AND` losing its meaning, or the field prefix colon being escaped into
    `%3A`, which the API reads as a different (empty) query.
    """
    url = cron_round.build_axis_url('all:"AI for science" AND all:agent', 20)
    assert "all:%22AI%20for%20science%22%20AND%20all:agent" in url
    assert "%2B" not in url
    assert "%3A" not in url


def test_build_axis_url_preserves_explicit_plus_operators() -> None:
    """The `A+AND+B` notation must survive intact -- `%2B` is what silently matches nothing."""
    url = cron_round.build_axis_url("all:verification+AND+all:agent", 5)
    assert "all:verification+AND+all:agent" in url
    assert "%2B" not in url


def test_build_axis_url_carries_window_and_sorting() -> None:
    url = cron_round.build_axis_url("all:verification", 7)
    assert "max_results=7" in url
    assert "sortBy=submittedDate" in url and "sortOrder=descending" in url


@pytest.mark.parametrize("query", ["", "   "])
def test_build_axis_url_rejects_empty_query(query: str) -> None:
    with pytest.raises(ValueError):
        cron_round.build_axis_url(query, 5)


# ----------------------------------------------------------------------------------------- year fill


@pytest.mark.parametrize(
    ("published", "expected"),
    [("2026-10-08", 2026), ("2026-10-08T12:00:00Z", 2026), ("", 0), ("unknown", 0)],
)
def test_year_from_published(published: str, expected: int) -> None:
    assert cron_round.year_from_published(published) == expected


# ---------------------------------------------------------------------------------- feed enrichment


def test_extract_summaries_collapses_whitespace_and_strips_markup() -> None:
    xml = "<entry><summary>a\n  b <b>c</b></summary></entry><entry><summary>second</summary></entry>"
    assert cron_round.extract_summaries(xml) == ["a b c", "second"]


def test_merge_rows_aligns_abstracts_positionally() -> None:
    rows = [{"id": "2610.00001"}, {"id": "2610.00002"}]
    merged = cron_round.merge_rows_with_summaries(rows, ["first", "second"])
    assert [row["abstract"] for row in merged] == ["first", "second"]
    assert merged[0]["id"] == "2610.00001"


def test_merge_rows_degrades_to_empty_abstracts_on_mismatch() -> None:
    """A count mismatch must not shift abstracts onto the wrong papers."""
    inside = cron_round.merge_rows_with_summaries([{"id": "2610.00001"}], ["one", "two"])
    assert inside[0]["abstract"] == ""

    outside = cron_round.merge_rows_with_summaries([{"id": "a"}, {"id": "b"}], ["one"])
    assert [row["abstract"] for row in outside] == ["", ""]


# ----------------------------------------------------------------------------------------- store diff


def test_select_new_treats_versioned_stored_form_as_already_filed() -> None:
    """The heart of the fix: a stored `v1` must make the bare candidate count as filed."""
    filed_forms = {"2609.09203v1"}
    is_filed = lambda bare: f"{bare}v1" in filed_forms  # noqa: E731
    new, filed = cron_round.select_new(["2609.09203", "2610.06986"], is_filed)
    assert filed == ["2609.09203"]
    assert new == ["2610.06986"]


def test_select_new_preserves_candidate_order() -> None:
    new, _ = cron_round.select_new(["2610.00003", "2610.00001", "2610.00002"], lambda _bare: False)
    assert new == ["2610.00003", "2610.00001", "2610.00002"]


def test_select_new_deduplicates_within_the_candidate_list() -> None:
    """An axis can return the same paper twice; it must be ingested once."""
    new, _ = cron_round.select_new(["2610.06986v1", "2610.06986", "2610.06986v2"], lambda _b: False)
    assert new == ["2610.06986"]


def test_find_stored_form_probes_beyond_the_bare_form() -> None:
    store = FakeStore(["2609.09203v3"])
    assert cron_round.find_stored_form(store, "2609.09203") == "2609.09203v3"


def test_find_stored_form_returns_none_when_absent() -> None:
    store = FakeStore(["2610.00001"])
    assert cron_round.find_stored_form(store, "2609.09203") is None


def test_find_stored_form_matches_the_bare_form_itself() -> None:
    store = FakeStore(["2609.09203"])
    assert cron_round.find_stored_form(store, "2609.09203") == "2609.09203"


# ------------------------------------------------------------------- ingest identity / year backfill


def test_resolve_ingest_id_reuses_the_stored_versioned_form() -> None:
    """The dedup hole measured on 2026-10-16: a re-post must land on the stored row, not beside it."""
    store = FakeStore(["2610.08691v1"])
    assert cron_round.resolve_ingest_id(store, "2610.08691") == "2610.08691v1"


def test_resolve_ingest_id_falls_back_to_the_bare_id() -> None:
    store = FakeStore(["2610.00001"])
    assert cron_round.resolve_ingest_id(store, "2610.08691") == "2610.08691"


def test_stored_year_missing_treats_zero_as_unfilled() -> None:
    store = FakeStore(["2610.08691v1"])
    assert cron_round.stored_year_missing(store, 1) is True
    store.years[1] = 2026
    assert cron_round.stored_year_missing(store, 1) is False


def test_ingest_one_posts_the_stored_form_and_backfills_a_zero_year(monkeypatch) -> None:
    """Both guarantees in one place, because they are only worth anything on the write path.

    The fake `ensure_paper` records the id it received -- that is the observable that distinguishes
    "re-used the stored row" from "forked a duplicate" -- and reports `is_new=False`, i.e. a paper
    the store already had under `v1`. The year must still be filled in, since the stored row has 0.
    """
    received: list[str] = []

    fake_module = ModuleType("hfpapers.paper_store")

    def fake_ensure_paper(arxiv_id: str, **_kwargs):
        received.append(arxiv_id)
        return 4242, False

    fake_module.ensure_paper = fake_ensure_paper  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hfpapers.paper_store", fake_module)

    store = FakeStore(["2610.08691v1"])
    result = cron_round.ingest_one(
        store, {"arxiv_id": "2610.08691", "published": "2026-10-07T01:02:03Z"}, "cron-test"
    )

    assert received == ["2610.08691v1"], "a re-post must dedup on the stored form"
    assert store.updates == [(4242, {"year": 2026})], "year=0 in the store must be repaired"
    assert result == {"arxiv_id": "2610.08691", "sf_id": 4242, "is_new": False, "year": 2026}


def test_ingest_one_leaves_a_known_year_alone(monkeypatch) -> None:
    """No write when the store already carries a year -- the backfill must not churn every round."""
    fake_module = ModuleType("hfpapers.paper_store")
    fake_module.ensure_paper = lambda arxiv_id, **_kwargs: (7, False)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hfpapers.paper_store", fake_module)

    store = FakeStore(["2610.08691v1"])
    store.years[7] = 2026
    cron_round.ingest_one(store, {"arxiv_id": "2610.08691", "published": "2026-10-07T01:02:03Z"}, "s")

    assert store.updates == []


# --------------------------------------------------------------------------------------- store audit


def test_audit_duplicated_forms_flags_the_measured_case() -> None:
    """`2609.09203` and `2609.09203v1` both live in the store as separate rows."""
    store = FakeStore(["2609.09203", "2609.09203v1", "2610.06986"])
    assert cron_round.audit_duplicated_forms(store) == {"2609.09203": ["2609.09203", "2609.09203v1"]}


def test_audit_duplicated_forms_is_empty_for_a_clean_store() -> None:
    store = FakeStore(["2610.06986", "2609.37603v1"])
    assert cron_round.audit_duplicated_forms(store) == {}


def test_audit_duplicated_forms_skips_non_arxiv_values() -> None:
    store = FakeStore(["10.1017/s0022377823000880", "2610.06986"])
    assert cron_round.audit_duplicated_forms(store) == {}


# ------------------------------------------------------------- pick metadata (measured 2026-10-17)


def test_build_idlist_url_carries_every_pick() -> None:
    url = cron_round.build_idlist_url(["2610.14683", "2610.18449"])
    assert "id_list=2610.14683,2610.18449" in url
    assert "max_results=2" in url


@pytest.mark.parametrize("ids", [[], ["", "  "]])
def test_build_idlist_url_rejects_empty(ids: list[str]) -> None:
    with pytest.raises(ValueError):
        cron_round.build_idlist_url(ids)


def test_run_fetches_metadata_for_picks(monkeypatch) -> None:
    """Measured defect: `--pick` used to reach `ensure_paper` with title='' and year=0.

    The three rows written that way on 2026-10-17 were invisible to every later title/year query.
    This gate pins the fix at the write path: the pick must be enriched from the `id_list` feed
    before `ensure_paper` sees it.
    """
    import argparse

    from hfpapers import arxiv_lookup as real_arxiv

    feed = b"""<feed><entry><id>http://arxiv.org/abs/2610.14683v1</id>
    <title>A Real Title</title><published>2026-10-10T07:55:42Z</published>
    <summary>An abstract worth storing.</summary></entry></feed>"""

    fake_store_mod = ModuleType("hfpapers.paper_store")
    fake_store_mod.get_store = lambda: FakeStore([])  # type: ignore[attr-defined]
    fake_store_mod.store_stats = lambda: {"papers_total": 0}  # type: ignore[attr-defined]
    received: list[dict] = []

    def fake_ensure_paper(arxiv_id, **kwargs):
        received.append({"arxiv_id": arxiv_id, **kwargs})
        return 99, True

    fake_store_mod.ensure_paper = fake_ensure_paper  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hfpapers.paper_store", fake_store_mod)

    fake_arxiv = ModuleType("hfpapers.arxiv_lookup")
    fake_arxiv.Pacing = lambda: SimpleNamespace(wait=lambda: None, note=lambda _n: None)  # type: ignore[attr-defined]
    fake_arxiv.parse_feed = real_arxiv.parse_feed  # type: ignore[attr-defined]
    fake_arxiv._http_get = lambda _url, timeout=0.0: (200, feed)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hfpapers.arxiv_lookup", fake_arxiv)

    args = argparse.Namespace(
        source="cron-test", axis=[], pick=["2610.14683"], dedup_regression=[],
        max_results=5, dry_run=False, audit_forms=False, json_out="",
    )
    summary, code = cron_round._run(args)

    assert code == 0
    assert received and received[0]["title"] == "A Real Title"
    assert received[0]["abstract"] == "An abstract worth storing."
    assert summary["ingested"][0]["year"] == 2026


def test_run_refuses_a_pick_the_feed_does_not_return(monkeypatch) -> None:
    """No metadata -> UsageError, never a title-less shell in the store."""
    import argparse

    fake_store_mod = ModuleType("hfpapers.paper_store")
    fake_store_mod.get_store = lambda: FakeStore([])  # type: ignore[attr-defined]
    fake_store_mod.store_stats = lambda: {"papers_total": 0}  # type: ignore[attr-defined]
    fake_store_mod.ensure_paper = lambda *a, **k: (1, True)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hfpapers.paper_store", fake_store_mod)

    fake_arxiv = ModuleType("hfpapers.arxiv_lookup")
    fake_arxiv.Pacing = lambda: SimpleNamespace(wait=lambda: None, note=lambda _n: None)  # type: ignore[attr-defined]
    fake_arxiv.parse_feed = lambda _t: []  # type: ignore[attr-defined]
    fake_arxiv._http_get = lambda _url, timeout=0.0: (200, b"<feed></feed>")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hfpapers.arxiv_lookup", fake_arxiv)

    args = argparse.Namespace(
        source="cron-test", axis=[], pick=["2610.99999"], dedup_regression=[],
        max_results=5, dry_run=False, audit_forms=False, json_out="",
    )
    with pytest.raises(cron_round.UsageError):
        cron_round._run(args)


# ---------------------------------------------------------------------------------------- regression


def test_evaluate_regression_is_silent_when_a_repost_is_correctly_deduped() -> None:
    probes = [{"arxiv_id": "2610.06986", "is_new": False}]
    assert cron_round.evaluate_regression(probes) == []


def test_evaluate_regression_names_the_offending_id() -> None:
    """`is_new=True` on a re-posted id means the dedup path is broken, and must fail the run."""
    probes = [{"arxiv_id": "2610.06986", "is_new": True}, {"arxiv_id": "2609.37603", "is_new": False}]
    violations = cron_round.evaluate_regression(probes)
    assert len(violations) == 1
    assert "2610.06986" in violations[0]
