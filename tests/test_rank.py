"""Rank training tests (L1 learned re-ranking on hub audit trails)."""

import json

import pytest

lightgbm = pytest.importorskip("lightgbm")

from hfpapers.rank import build_dataset, load_audit, train

FEATURES = ["hub_score", "degree", "layer"]


def _write_synthetic_audit(path, n=40):
    """Synthetic audit: adopted papers have higher hub_score/degree."""
    rows = []
    for i in range(n):
        adopted = i % 2 == 0
        hub_score = (90.0 + (i % 10) * 1.5) if adopted else (20.0 + (i % 10))
        degree = (30 + i % 20) if adopted else (2 + i % 5)
        rows.append(
            {
                "layer": 1 + i % 3,
                "arxiv_id": f"26{i:02d}.{10000 + i:05d}",
                "adopted": adopted,
                "hub_score": hub_score,
                "degree": degree,
                "seed_depth": 1,
                "source": "s2_hub",
            }
        )
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return rows


def test_load_audit(tmp_path):
    p = tmp_path / "audit.jsonl"
    rows = _write_synthetic_audit(p)
    loaded = load_audit(p)
    assert len(loaded) == len(rows)
    assert loaded[0]["arxiv_id"]


def test_build_dataset_shapes(tmp_path):
    p = tmp_path / "audit.jsonl"
    _write_synthetic_audit(p)
    X, y, w = build_dataset(load_audit(p))  # noqa: N806
    assert len(X) == len(y) == len(w)
    assert len(X[0]) == len(FEATURES)
    assert set(y) == {0, 1}
    assert w == [1.0] * len(y)  # synthetic rows carry no weight → default 1.0


def test_build_dataset_carries_row_weights(tmp_path):
    """Pool layer weights (manual 3.0 / verified 2.0) are real training signal."""
    p = tmp_path / "audit.jsonl"
    with open(p, "w") as f:
        f.write(json.dumps({"arxiv_id": "2609.01001", "adopted": True,
                            "hub_score": 0.9, "degree": 5}) + "\n")
        f.write(json.dumps({"arxiv_id": "2609.01002", "adopted": False,
                            "hub_score": 0.1, "degree": 1, "weight": 3.0}) + "\n")
    X, y, w = build_dataset(load_audit(p))  # noqa: N806
    assert y == [1, 0]
    assert w == [1.0, 3.0]


def test_train_learns_pattern(tmp_path):
    """Model should separate adopted (high hub) from truncated (low hub)."""
    p = tmp_path / "audit.jsonl"
    model_path = tmp_path / "rank_model.txt"
    _write_synthetic_audit(p)
    res = train(p, out_model=str(model_path), n_estimators=50)
    assert res["rows"] >= 4
    assert res["positives"] > 0 and res["negatives"] > 0
    assert res["features"] == FEATURES
    assert set(res["feature_importance"].keys()) == set(FEATURES)
    assert model_path.exists()
    # Model can predict: adopted candidate scores above truncated one
    import lightgbm as lgb

    booster = lgb.Booster(model_file=str(model_path))
    good = booster.predict([[95.0, 40.0, 1.0]])
    bad = booster.predict([[25.0, 3.0, 1.0]])
    assert good[0] > bad[0]


def test_train_too_small(tmp_path):
    p = tmp_path / "audit.jsonl"
    with open(p, "w") as f:
        for i in range(2):
            f.write(json.dumps({"arxiv_id": f"2601.{i:05d}", "adopted": bool(i),
                                "hub_score": 1.0, "degree": 1, "layer": 1}) + "\n")
    with pytest.raises(ValueError):
        train(p)


def test_train_no_rows(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    with pytest.raises(ValueError):
        train(p)
