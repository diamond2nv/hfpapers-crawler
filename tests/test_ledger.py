"""Ledger + check-new tests (run-level accounting & 0-token change detection)."""

from hfpapers.ledger import check_new, ledger_path, log, recent, stats
from hfpapers.paper_store import PaperStore


def _store(tmp_path):
    return PaperStore(db_path=str(tmp_path / "test.db"))


def test_log_append_and_recent(tmp_path):
    row = log(tmp_path, event="import", source="arxiv", sf_id_delta=5,
              llm_cost=0.0123, next_hypothesis="raise relevance floor")
    assert row["sf_id_delta"] == 5
    assert row["llm_cost"] == 0.0123
    log(tmp_path, event="audit", source="openalex")
    rows = recent(tmp_path, limit=10)
    assert len(rows) == 2
    assert rows[0]["event"] == "audit"  # newest first
    assert ledger_path(tmp_path).exists()


def test_stats_aggregation(tmp_path):
    log(tmp_path, event="import", sf_id_delta=10, llm_cost=0.01)
    log(tmp_path, event="import", sf_id_delta=3, llm_cost=0.02)
    log(tmp_path, event="audit")
    st = stats(tmp_path)
    assert st["rows"] == 3
    assert st["sf_id_delta"] == 13
    assert abs(st["llm_cost_total"] - 0.03) < 1e-9
    assert st["by_event"]["import"] == 2


def test_stats_empty_and_corrupt_line(tmp_path):
    st = stats(tmp_path)
    assert st["rows"] == 0
    # corrupt trailing write must not crash stats/recent
    ledger_path(tmp_path).write_text('{"event": "ok"}\nnot-json\n', encoding="utf-8")
    st2 = stats(tmp_path)
    assert st2["rows"] == 1
    assert recent(tmp_path, limit=5)  # corrupt line skipped


def test_check_new_zero_token_gate(tmp_path):
    store = _store(tmp_path)
    # first check = baseline (new_papers 0 because store empty → total 0)
    r1 = check_new(store, tmp_path)
    assert r1["new_papers"] == 0
    assert r1["total"] == 0
    # identical second check → NO_CHANGE semantics (monitor gate skips LLM)
    r2 = check_new(store, tmp_path)
    assert r2["new_papers"] == 0
    # add a paper → next check reports the delta
    with store._lock, store._conn() as conn:
        conn.execute("INSERT INTO papers (title) VALUES ('New Paper')")
    r3 = check_new(store, tmp_path)
    assert r3["new_papers"] == 1
    assert r3["total"] == 1
    # and after that, stable again (identical output when nothing changed)
    r4 = check_new(store, tmp_path)
    assert r4["new_papers"] == 0
    assert r4["total"] == 1


def test_check_new_uses_existing_store_meta(tmp_path):
    store = _store(tmp_path)
    r = check_new(store, tmp_path)
    assert "first_new_id" in r
    assert "checked_at" in r
    # state file persisted
    assert (tmp_path / "check_new_state.json").exists()
