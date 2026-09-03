"""Recommendation tests (fused query pool + verification gate + why audit)."""

import pytest

from hfpapers.profile import RepoProfile
from hfpapers.recommend import build_query_pool, recommend

pytest.importorskip  # silence unused-import linters; pytest used below


def _store_with_papers(tmp_path):
    from hfpapers.paper_store import PaperStore

    store = PaperStore(db_path=str(tmp_path / "rec.db"))
    rows = [
        ("Fourier Neural Operator for PDE", "pde neural operator learning", 90),
        ("Physics-Informed Neural Networks", "physics informed deep learning", 85),
        ("Stellarator Coil Optimization", "fusion plasma magnetic design", 40),
        ("Graph Neural Network Surrogates", "gnn simulation surrogate", 70),
    ]
    ids = {}
    for title, abstract, rel in rows:
        with store._lock, store._conn() as conn:
            cur = conn.execute(
                "INSERT INTO papers (title, abstract, relevance) VALUES (?, ?, ?)",
                (title, abstract, rel),
            )
        ids[title] = cur.lastrowid
    return store, ids


def test_query_pool_fusion_priority(monkeypatch, tmp_path):
    # global (from config) + repo + user; repo wins ties
    import hfpapers.recommend as mod

    monkeypatch.setattr(
        mod, "_config_queries",
        lambda: [("neural operator", 1, "global"), ("shared topic", 1, "global")],
    )
    repo = RepoProfile(profile="x", queries=[{"query": "shared topic", "weight": 5}])
    user = RepoProfile(profile="u", queries=[{"query": "stellarator", "weight": 2}])
    monkeypatch.setattr(mod, "detect_profile", lambda d: repo)
    monkeypatch.setattr(mod, "user_profile", lambda: user)
    pool = build_query_pool()
    d = {q: (w, layer) for q, w, layer in pool}
    assert d["shared topic"] == (5, "repo")  # repo beats global on tie
    assert d["neural operator"] == (1, "global")
    assert d["stellarator"] == (2, "user")


def test_recommend_orders_and_why(tmp_path, monkeypatch):
    store, ids = _store_with_papers(tmp_path)
    import hfpapers.recommend as mod

    monkeypatch.setattr(mod, "_config_queries", lambda: [("neural operator", 2, "global")])
    monkeypatch.setattr(mod, "detect_profile", lambda d: RepoProfile())
    monkeypatch.setattr(mod, "user_profile", lambda: RepoProfile())
    results = recommend(store, limit=5, repo_dir=tmp_path)
    assert results, "expected at least one hit"
    top = results[0]
    assert top["sf_id"] == ids["Fourier Neural Operator for PDE"]
    assert top["why"], "why must be populated (auditable)"
    assert any(layer == "global" for layer, _ in top["why"])
    # scores descending
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_recommend_suspect_gated_out(tmp_path, monkeypatch):
    store, ids = _store_with_papers(tmp_path)
    import hfpapers.recommend as mod

    monkeypatch.setattr(mod, "_config_queries", lambda: [("neural", 2, "global")])
    monkeypatch.setattr(mod, "detect_profile", lambda d: RepoProfile())
    monkeypatch.setattr(mod, "user_profile", lambda: RepoProfile())
    # flag the top hit suspect → it must disappear, others remain (pending)
    store.mark_suspect(ids["Fourier Neural Operator for PDE"], "test conflict")
    results = recommend(store, limit=5, repo_dir=tmp_path)
    sf_ids = [r["sf_id"] for r in results]
    assert ids["Fourier Neural Operator for PDE"] not in sf_ids
    assert ids["Physics-Informed Neural Networks"] in sf_ids  # still recommended
    assert any(r["status"] == "pending" for r in results)
    # --no-gate equivalent: suspect reappears
    results_ungated = recommend(store, limit=5, repo_dir=tmp_path, status_gate=False)
    assert ids["Fourier Neural Operator for PDE"] in {r["sf_id"] for r in results_ungated}
