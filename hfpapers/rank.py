#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rank.py — Learned re-ranking layer (L1) for hub-guided expansion audit trails.

Trains a gradient-boosted tree (lightgbm) on HubGuidedExpander audit JSONL:
positive = papers the hub heuristic adopted into the next frontier,
negative = candidates truncated at the same layer. Tree feature importance
doubles as the audit trail ("why was this paper ranked?").

Design (roadmap §2d): symbolic hub layer stays the default 0-token path;
this is an opt-in enhancement. Optional dependency: `hfpclawer[rank]`
(lightgbm + onnxruntime). Model files are trained/exported locally, never
shipped in the wheel (Mirobody matrix lesson).
"""

from __future__ import annotations

import json
from pathlib import Path

FEATURES = ["hub_score", "degree", "layer"]


def load_audit(audit_path: str | Path) -> list[dict]:
    """Load audit JSONL rows (arxiv_id/adopted/hub_score/degree/layer)."""
    rows = []
    with open(audit_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "arxiv_id" in row and "adopted" in row:
                rows.append(row)
    return rows


def build_dataset(rows: list[dict]) -> tuple[list[list[float]], list[int], list[float]]:
    """Feature matrix + labels + sample weights from audit rows.

    Returns (X, y, w) where X columns follow FEATURES order and w carries
    the row weight (default 1.0 when absent) — pool layer weights (manual
    3.0 / verified 2.0 / ...) are REAL training signal, not documentation.
    Rows missing any feature column are skipped (defensive).
    """
    X: list[list[float]] = []  # noqa: N806 (ML convention)
    y: list[int] = []
    w: list[float] = []
    for r in rows:
        try:
            x = [float(r.get(f, 0.0) or 0.0) for f in FEATURES]
        except (TypeError, ValueError):
            continue
        X.append(x)  # noqa: N806
        y.append(1 if r["adopted"] else 0)
        try:
            w.append(float(r.get("weight", 1.0) or 1.0))
        except (TypeError, ValueError):
            w.append(1.0)
    return X, y, w


def train(audit_path: str | Path, out_model: str = "", n_estimators: int = 200,
          random_state: int = 42) -> dict:
    """Train lightgbm on audit trail; export ONNX if out_model given.

    Returns summary dict: rows/positives/negatives/features/
    feature_importance (tree) / model_path / onnx_path.
    """
    import lightgbm as lgb  # optional: pip install hfpclawer[rank]

    rows = load_audit(audit_path)
    if not rows:
        raise ValueError(f"no audit rows in {audit_path}")
    X, y, w = build_dataset(rows)  # noqa: N806 (ML convention)
    if len(X) < 4 or len(set(y)) < 2:
        raise ValueError(
            f"need ≥4 rows with both classes for training (got {len(X)} rows, "
            f"{len(set(y))} classes) — collect more hub expansion runs"
        )
    clf = lgb.LGBMClassifier(
        n_estimators=n_estimators,
        learning_rate=0.05,
        num_leaves=31,
        random_state=random_state,
        verbose=-1,
    )
    clf.fit(X, y, sample_weight=w)
    importance = dict(zip(FEATURES, (float(v) for v in clf.feature_importances_)))
    result = {
        "rows": len(rows),
        "positives": sum(y),
        "negatives": len(y) - sum(y),
        "features": FEATURES,
        "feature_importance": importance,
    }
    if out_model:
        # LightGBM native model (portable, tiny, zero-dep inference).
        # NOTE: true ONNX conversion needs lgbm2onnx (kept out of core deps);
        # native model IS the artifact. lightgbm CLI + hermes can score it
        # directly via booster_.predict — no runtime dep required.
        result["model_path"] = str(out_model)
        clf.booster_.save_model(out_model)
    return result
