"""State semantics tests (v0.16+ — SKILL.state: pending/suspect/verified/stale)."""

import pytest

from hfpapers.paper_store import PaperStore


@pytest.fixture()
def store(tmp_path):
    """Isolated PaperStore per test (direct db_path injection)."""
    return PaperStore(db_path=str(tmp_path / "test_papers.db"))


def _insert_paper(store, title="Test Paper", audit_level=0, audit_at="", verified=0):
    with store._lock, store._conn() as conn:
        cur = conn.execute(
            "INSERT INTO papers (title, audit_level, audit_level_at, verified) "
            "VALUES (?, ?, ?, ?)",
            (title, audit_level, audit_at, verified),
        )
        sf_id = cur.lastrowid
    return sf_id


def test_migration_adds_suspect_columns(store):
    """Migration v3 idempotent: suspect/suspect_at exist after init."""
    with store._conn() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(papers)")}
    assert "suspect" in cols
    assert "suspect_at" in cols
    # Re-init is a no-op (idempotent migration)
    store._init_db()


def test_default_status_pending(store):
    sf_id = _insert_paper(store, audit_level=0)
    st = store.get_status(sf_id)
    assert st["status"] == "pending"
    assert st["audit_level"] == 0


def test_audit_level_1_verified(store):
    sf_id = _insert_paper(store, audit_level=1, audit_at="2026-09-01 10:00:00")
    st = store.get_status(sf_id)
    assert st["status"] == "verified"


def test_suspect_first_class(store):
    sf_id = _insert_paper(store, audit_level=1, audit_at="2026-09-01 10:00:00")
    store.mark_suspect(sf_id, "DOI resolves to different arXiv ID")
    st = store.get_status(sf_id)
    # Suspect overrides verified — explicit abstain is first-class
    assert st["status"] == "suspect"
    assert "different arXiv ID" in st["reason"]
    assert st["since"] != ""

    store.clear_suspect(sf_id)
    st2 = store.get_status(sf_id)
    # After adjudication, returns to verified per audit_level
    assert st2["status"] == "verified"


def test_stale_detection(store):
    old = "2020-01-01 00:00:00"
    sf_id = _insert_paper(store, audit_level=1, audit_at=old)
    st = store.get_status(sf_id, stale_days=180)
    assert st["status"] == "stale"
    # Recent verification is not stale
    sf_id2 = _insert_paper(store, audit_level=1, audit_at="2026-09-01 00:00:00")
    st2 = store.get_status(sf_id2, stale_days=180)
    assert st2["status"] == "verified"


def test_status_summary_counts(store):
    _insert_paper(store, audit_level=0)  # pending
    _insert_paper(store, audit_level=1, audit_at="2026-09-01 10:00:00")  # verified
    _insert_paper(store, audit_level=1, audit_at="2020-01-01 10:00:00")  # stale
    s = store.status_summary(stale_days=180)
    assert s["pending"] == 1
    assert s["verified"] == 1
    assert s["stale"] == 1
    assert s["suspect"] == 0
    # mark suspect on the verified one
    # mark suspect on the verified one (direct update simulates audit conflict path)
    with store._lock, store._conn() as conn:
        conn.execute("UPDATE papers SET suspect='x', suspect_at=datetime('now') WHERE audit_level=1 AND audit_level_at LIKE '2026%'")
    s2 = store.status_summary(stale_days=180)
    assert s2["suspect"] == 1
    assert s2["verified"] == 0


def test_mark_suspect_unknown_id_no_crash(store):
    # Marking a non-existent id just updates 0 rows — no crash
    store.mark_suspect(999999, "ghost")
    st = store.get_status(999999)
    assert st["status"] == "unknown"


def test_identifier_conflict_detection(store):
    """DOI (via crossref_cache) resolving to a different arXiv ID = conflict."""
    sf_id = _insert_paper(store, title="Conflict Paper")
    with store._lock, store._conn() as conn:
        conn.execute(
            "INSERT INTO identifiers (sf_id, id_type, id_value, source) VALUES (?, 'arxiv', '2601.00001', 'test')",
            (sf_id,),
        )
        conn.execute(
            "INSERT INTO identifiers (sf_id, id_type, id_value, source) VALUES (?, 'doi', '10.1000/conflict', 'test')",
            (sf_id,),
        )
        conn.execute(
            "INSERT INTO crossref_cache (doi, title, arxiv_id) VALUES ('10.1000/conflict', 'Conflict Paper', '2601.99999')",
        )
    conflicts = store.detect_identifier_conflicts()
    assert len(conflicts) == 1
    assert conflicts[0]["arxiv_id"] == "2601.00001"
    assert conflicts[0]["doi_arxiv"] == "2601.99999"

    # Matching arXiv ID → no conflict
    with store._lock, store._conn() as conn:
        conn.execute("UPDATE crossref_cache SET arxiv_id='2601.00001' WHERE doi='10.1000/conflict'")
    assert store.detect_identifier_conflicts() == []


def test_verify_paper_still_works(store):
    """verify_paper path intact after migration."""
    sf_id = _insert_paper(store)
    with store._lock, store._conn() as conn:
        conn.execute(
            "INSERT INTO identifiers (sf_id, id_type, id_value, source) VALUES (?, 'arxiv', '2602.00002', 'test')",
            (sf_id,),
        )
        conn.execute(
            "INSERT INTO identifiers (sf_id, id_type, id_value, source) VALUES (?, 'doi', '10.1000/x', 'test')",
            (sf_id,),
        )
    assert store.verify_paper(sf_id) is True
    assert store.get_audit_level(sf_id) == 1
