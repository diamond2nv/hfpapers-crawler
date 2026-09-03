"""Pool tests: layered positive examples, live gates, adjudication, export."""

import json

import pytest

from hfpapers.paper_store import PaperStore
from hfpapers.pool import (
    add_manual,
    default_pool_path,
    export_rows,
    ingest_audit,
    ingest_verified,
    stats,
    sync_favorited,
    sync_profile_accepted,
)


@pytest.fixture
def store(tmp_path):
    return PaperStore(db_path=str(tmp_path / "t.db"))


def _insert(store, aid, title="T", audit_level=0, suspect="", favorited=0):
    """Insert paper + arxiv identifier directly (test_state convention)."""
    with store._lock, store._conn() as conn:
        cur = conn.execute(
            "INSERT INTO papers (title, abstract, source, audit_level, "
            "suspect, favorited) VALUES (?, ?, ?, ?, ?, ?)",
            (title, "abstract", "arxiv", audit_level, suspect, favorited),
        )
        sf = cur.lastrowid
        conn.execute(
            "INSERT INTO identifiers (sf_id, id_type, id_value) VALUES (?, 'arxiv', ?)",
            (sf, aid),
        )
    return sf


def _audit_file(tmp_path, rows):
    p = tmp_path / "audit.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return p


def test_empty_pool_stats(store, tmp_path):
    st = stats(pool=str(tmp_path / "p.jsonl"), store=store)
    assert st["total"] == 0


def test_ingest_audit_folds_adopted_and_truncated(tmp_path):
    audit = _audit_file(tmp_path, [
        {"arxiv_id": "2609.00001", "adopted": True, "hub_score": 0.9, "degree": 5},
        {"arxiv_id": "2609.00002", "adopted": False, "hub_score": 0.2, "degree": 1},
    ])
    pool = tmp_path / "p.jsonl"
    added = ingest_audit(audit, pool=pool)
    assert added == {"adopted": 1, "truncated": 1}
    rows = export_rows(pool=pool)
    assert len(rows) == 2
    by_id = {r["arxiv_id"]: r for r in rows}
    assert by_id["2609.00001"]["adopted"] is True
    assert by_id["2609.00002"]["adopted"] is False
    assert by_id["2609.00001"]["hub_score"] == 0.9


def test_ingest_audit_idempotent_same_source_run(tmp_path):
    audit = _audit_file(tmp_path, [
        {"arxiv_id": "2609.00001", "adopted": True, "hub_score": 0.9},
    ])
    pool = tmp_path / "p.jsonl"
    ingest_audit(audit, pool=pool)  # source_run defaults to audit filename
    ingest_audit(audit, pool=pool)  # re-ingest same file → no dupes
    rows = export_rows(pool=pool)
    assert len(rows) == 1
    assert stats(pool=str(pool))["total"] == 1


def test_ingest_verified_folds_verified_only(store, tmp_path):
    _insert(store, "2609.00010", audit_level=3)   # human-approved → in
    _insert(store, "2609.00011", audit_level=1)   # metadata-verified → in (get_status)
    _insert(store, "2609.00012", audit_level=0)   # unaudited → out
    _insert(store, "2609.00013", audit_level=2, suspect="conflict")  # suspect → gated
    pool = tmp_path / "p.jsonl"
    added = ingest_verified(store, pool=pool)
    assert added == {"verified": 2}
    rows = export_rows(pool=pool, store=store)
    aids = {r["arxiv_id"] for r in rows}
    assert aids == {"2609.00010", "2609.00011"}


def test_sync_favorited_folds_only_favorited(store, tmp_path):
    _insert(store, "2609.00020", favorited=1)
    _insert(store, "2609.00021")  # not favorited
    pool = tmp_path / "p.jsonl"
    added = sync_favorited(store, pool=pool)
    assert added == {"favorited": 1}


def test_add_manual_strongest_layer_and_validation(store, tmp_path):
    _insert(store, "2609.00030")
    pool = tmp_path / "p.jsonl"
    r = add_manual(store, "2609.00030", reason="key paper", pool=pool)
    assert r["manual"] == 1
    # unknown paper → error, nothing written
    r2 = add_manual(store, "9999.99999", pool=pool)
    assert "error" in r2
    assert stats(pool=str(pool))["total"] == 1
    # suspect paper cannot be a positive example
    _insert(store, "2609.00031", suspect="unverifiable")
    r3 = add_manual(store, "2609.00031", pool=pool)
    assert "error" in r3
    assert stats(pool=str(pool))["total"] == 1


def test_append_only_never_rewrites(tmp_path):
    audit1 = _audit_file(tmp_path, [{"arxiv_id": "2609.00040", "adopted": True}])
    pool = tmp_path / "p.jsonl"
    ingest_audit(audit1, pool=pool, source_run="run1")
    audit2 = _audit_file(tmp_path, [{"arxiv_id": "2609.00041", "adopted": False}])
    ingest_audit(audit2, pool=pool, source_run="run2")
    # history preserved: both runs present, file is append-only
    with open(pool, encoding="utf-8") as f:
        lines = [line for line in f if line.strip()]
    assert len(lines) == 2


def test_label_adjudication_verified_beats_truncated(store, tmp_path):
    """Same paper adopted in one run, truncated in another + human-approved later.

    verified (priority 0) must beat truncated (priority 4) → final +1.
    """
    _insert(store, "2609.00050", audit_level=3)
    audit = _audit_file(tmp_path, [{"arxiv_id": "2609.00050", "adopted": False}])
    pool = tmp_path / "p.jsonl"
    ingest_audit(audit, pool=pool)
    ingest_verified(store, pool=pool)
    rows = export_rows(pool=pool, store=store)
    match = [r for r in rows if r["arxiv_id"] == "2609.00050"]
    assert len(match) == 1  # adjudicated to a single row
    assert match[0]["adopted"] is True
    assert match[0]["layer"] == "verified"


def test_live_suspect_filter_at_export(store, tmp_path):
    """Paper suspect AFTER pool entry → export filters it, pool keeps it."""
    _insert(store, "2609.00060", audit_level=3)
    pool = tmp_path / "p.jsonl"
    ingest_verified(store, pool=pool)
    assert len(export_rows(pool=pool, store=store)) == 1
    # paper becomes suspect later → live gate drops it from training export
    paper = store.find_paper_by_any_id("2609.00060")
    store.mark_suspect(paper.sf_id, reason="DOI conflict")
    assert len(export_rows(pool=pool, store=store)) == 0
    assert stats(pool=str(pool), store=store)["suspect_pending_export_filter"] == 1
    # pool file itself unchanged (append-only, reversible)
    assert stats(pool=str(pool))["total"] == 1
    # cleared suspect → usable again
    store.clear_suspect(paper.sf_id)
    assert len(export_rows(pool=pool, store=store)) == 1


def test_corrupt_line_skipped(tmp_path):
    pool = tmp_path / "p.jsonl"
    pool.write_text('{"arxiv_id": "2609.00070", "layer": "adopted", "label": 1}\nNOT JSON\n')
    rows = export_rows(pool=pool)
    assert len(rows) == 1


def test_default_pool_path_in_data_dir():
    p = default_pool_path()
    assert p.name == "positive_pool.jsonl"
    assert "data" in str(p)


def test_sync_profile_accepted_folds_paper_declarations(store, tmp_path):
    """Active paper-level accept declarations → manual pool layer (w=3.0)."""
    from hfpapers.profile import ProfileVerdict, RepoProfile

    _insert(store, "2609.00080")
    _insert(store, "2609.00081")
    _insert(store, "2609.00082", suspect="bad")
    prof = RepoProfile(
        accepts=[
            ProfileVerdict(verdict="accept", type="paper", state="active",
                           name="key paper", identifiers={"arxiv": "2609.00080"}),
            ProfileVerdict(verdict="accept", type="paper", state="active",
                           identifiers={"arxiv": "2609.00081"}),
            ProfileVerdict(verdict="accept", type="paper", state="active",
                           identifiers={"arxiv": "2609.00082"}),  # suspect → error
            ProfileVerdict(verdict="accept", type="paper", state="superseded",
                           identifiers={"arxiv": "2609.00080"}),  # inert
            ProfileVerdict(verdict="accept", type="method", state="active",
                           name="lightgbm"),  # not paper-type → skipped
        ]
    )
    pool = tmp_path / "p.jsonl"
    result = sync_profile_accepted(store, prof, pool=pool)
    assert result["manual"] == 2
    assert any("2609.00082" in e for e in result["errors"])
    rows = export_rows(pool=pool)
    assert len(rows) == 2
    assert all(r["weight"] == 3.0 for r in rows)  # manual layer strength
