#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pool.py — open-source positive-example pool (roadmap §2e, v0.16.8).

Every clone user bootstraps with zero config: run imports + hub expansion,
ingest the audit trail, and the pool accumulates learnable signal. No labels,
no personal profile, no Zotero required. Pool file lives in data/ (gitignored,
append-only, never telemetry).

Row schema (JSONL, one sample per line):
    {"arxiv_id", "label": +1|0, "layer", "weight", "ts", "source_run", "features": {}}

Layer = label source with confidence weighting, decoupled from any user/repo:
    verified   +1 w=2.0  store audit_level=3 (human-approved)  — any user has these
    manual     +1 w=3.0  explicit `pool add` (strongest)
    favorited  +1 w=1.5  Zotero sync-back interest (optional)
    adopted    +1 w=1.0  hub heuristic adoption (weak label — behavior cloning)
    truncated   0 w=1.0  same-layer truncated candidates (weak negatives)
    suspect papers NEVER enter the pool (abstain ≠ negative).

Live gates (pool pollution control — COVERAGE_FLOOR ratchet):
    1. entry: store-known suspect papers rejected at ingest/add
    2. train-time: pool stays append-only; export filters CURRENT suspect papers
    3. label adjudication: same arxiv_id with conflicting layers → highest
       priority layer wins (verified > manual > favorited > adopted > truncated)
    4. rank train already enforces min-rows + both-classes (COVERAGE_FLOOR)
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

# Layer semantics: label + default weight + adjudication priority (index).
_LAYER_ORDER = ["verified", "manual", "favorited", "adopted", "truncated"]
LAYER_LABEL = {"verified": 1, "manual": 1, "favorited": 1, "adopted": 1, "truncated": 0}
LAYER_WEIGHT = {"verified": 2.0, "manual": 3.0, "favorited": 1.5, "adopted": 1.0, "truncated": 1.0}

POOL_FILENAME = "positive_pool.jsonl"


def default_pool_path() -> Path:
    """data/positive_pool.jsonl — same resolution as paper_store._db_path."""
    pkg_root = Path(__file__).parent.parent
    env_dir = os.environ.get("HFPAPERS_DATA_DIR")
    if env_dir:
        base = env_dir if os.path.isabs(env_dir) else str(pkg_root / env_dir)
    else:
        base = str(pkg_root / "data")
    return Path(base) / POOL_FILENAME


def _load_rows(pool: str | Path) -> list[dict]:
    """Defensive read — skip blank/corrupt lines (plain-dict mechanical layer)."""
    rows = []
    path = Path(pool)
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except (ValueError, TypeError):
                continue  # corrupt line: skip, never crash the pool
            if "arxiv_id" in row and "layer" in row:
                rows.append(row)
    return rows


def _existing_keys(pool: str | Path) -> set[tuple]:
    """(arxiv_id, layer, source_run) keys already in the pool (idempotency)."""
    return {(r["arxiv_id"], r["layer"], r.get("source_run", "")) for r in _load_rows(pool)}


def _append_rows(pool: str | Path, rows: list[dict]) -> None:
    """Append-only writes (never overwrite, never rewrite history)."""
    path = Path(pool)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _make_row(arxiv_id: str, layer: str, source_run: str = "",
              features: dict | None = None, ts: str = "") -> dict:
    return {
        "arxiv_id": arxiv_id,
        "label": LAYER_LABEL[layer],
        "layer": layer,
        "weight": LAYER_WEIGHT[layer],
        "ts": ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_run": source_run,
        "features": features or {},
    }


# ─── Ingest paths ────────────────────────────────────────────────────────


def ingest_audit(audit_path: str | Path, pool: str | Path | None = None,
                 source_run: str = "") -> dict:
    """Fold hub-expansion audit rows into the pool.

    adopted=true → +1 adopted layer; adopted=false → 0 truncated layer.
    Idempotent per (arxiv_id, layer, source_run). No store needed — every
    clone user who runs expand-hub --audit has this.
    """
    pool = pool or default_pool_path()
    existing = _existing_keys(pool)
    added = {"adopted": 0, "truncated": 0}
    with open(audit_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except (ValueError, TypeError):
                continue
            aid = row.get("arxiv_id")
            if not aid or "adopted" not in row:
                continue
            layer = "adopted" if row["adopted"] else "truncated"
            run = source_run or str(Path(audit_path).name)
            if (aid, layer, run) in existing:
                continue
            feat = {k: row.get(k) for k in ("hub_score", "degree", "layer", "community")
                    if k in row}
            _append_rows(pool, [_make_row(aid, layer, source_run=run, features=feat)])
            existing.add((aid, layer, run))
            added[layer] += 1
    return added


def _paper_arxiv_ids(store, sf_ids: list[int]) -> dict[int, str]:
    """sf_id → arXiv identifier (first arxiv id_type found)."""
    out = {}
    for sf in sf_ids:
        for ident in store.get_identifiers(sf):
            if ident.id_type == "arxiv":
                out[sf] = ident.id_value
                break
    return out


def _store_suspect_ids(store) -> set[int]:
    """sf_ids currently marked suspect (entry gate: abstain ≠ negative)."""
    out = set()
    for p in store.get_all_papers():
        if p.suspect:
            out.add(p.sf_id)
    return out


def ingest_verified(store, pool: str | Path | None = None, source_run: str = "") -> dict:
    """Fold store-verified papers (status==verified, i.e. audit_level≥1) as +1 verified.

    Mirrors get_status semantics: audit_level≥1 = verified (suspect overrides).
    Any clone user with imported + verified papers has this signal.
    """
    pool = pool or default_pool_path()
    existing = _existing_keys(pool)
    suspect = _store_suspect_ids(store)
    papers = store.get_all_papers()
    by_sf = {p.sf_id: p for p in papers}
    candidates = [p for p in papers if p.audit_level >= 1 and p.sf_id not in suspect]
    arxiv = _paper_arxiv_ids(store, [p.sf_id for p in candidates])
    added = 0
    rows = []
    for sf, aid in arxiv.items():
        if (aid, "verified", source_run) in existing:
            continue
        rows.append(_make_row(aid, "verified", source_run=source_run,
                              features={"sf_id": sf,
                                        "audit_level": by_sf[sf].audit_level}))
        added += 1
    _append_rows(pool, rows)
    return {"verified": added}


def sync_favorited(store, pool: str | Path | None = None, source_run: str = "") -> dict:
    """Fold Zotero-synced favorites into the pool as +1 favorited (optional layer)."""
    pool = pool or default_pool_path()
    existing = _existing_keys(pool)
    suspect = _store_suspect_ids(store)
    papers = store.get_all_papers()
    by_sf = {p.sf_id: p for p in papers}
    candidates = [p for p in papers if p.favorited and p.sf_id not in suspect]
    arxiv = _paper_arxiv_ids(store, [p.sf_id for p in candidates])
    added = 0
    rows = []
    for sf, aid in arxiv.items():
        if (aid, "favorited", source_run) in existing:
            continue
        rows.append(_make_row(aid, "favorited", source_run=source_run,
                              features={"sf_id": sf, "favorited_at": by_sf[sf].favorited_at}))
        added += 1
    _append_rows(pool, rows)
    return {"favorited": added}


def add_manual(store, arxiv_id: str, reason: str = "",
               pool: str | Path | None = None) -> dict:
    """Explicit positive example (strongest layer, w=3.0).

    Paper must exist in store and must not be suspect. Returns stats or
    {"error": msg} when the paper is unknown/suspect.
    """
    pool = pool or default_pool_path()
    paper = store.find_paper_by_any_id(arxiv_id)
    if paper is None:
        return {"error": f"paper not in store: {arxiv_id}"}
    if paper.suspect:
        return {"error": f"suspect paper cannot be a positive example: {arxiv_id}"}
    _append_rows(pool, [_make_row(arxiv_id, "manual", source_run="manual",
                                  features={"sf_id": paper.sf_id, "reason": reason})])
    return {"manual": 1, "sf_id": paper.sf_id}


# ─── Stats / export (live gates) ─────────────────────────────────────────


def stats(pool: str | Path | None = None, store=None) -> dict:
    """Layer distribution / label balance / suspect-pending count (ratchet view)."""
    pool = pool or default_pool_path()
    rows = _load_rows(pool)
    by_layer = {layer: 0 for layer in _LAYER_ORDER}
    positives = negatives = 0
    for r in rows:
        by_layer[r["layer"]] = by_layer.get(r["layer"], 0) + 1
        if r["label"] == 1:
            positives += 1
        else:
            negatives += 1
    suspect_pending = 0
    if store and rows:
        ids = {r["arxiv_id"] for r in rows}
        suspect = _store_suspect_ids(store)
        for p in store.get_all_papers():
            for ident in store.get_identifiers(p.sf_id):
                if ident.id_type == "arxiv" and ident.id_value in ids and p.sf_id in suspect:
                    suspect_pending += 1
    return {
        "total": len(rows),
        "by_layer": by_layer,
        "positives": positives,
        "negatives": negatives,
        "ratio_pos": round(positives / max(1, negatives), 2),
        "suspect_pending_export_filter": suspect_pending,
    }


def export_rows(pool: str | Path | None = None, store=None) -> list[dict]:
    """Live-gated training rows (audit-compatible, consumable by rank.train).

    Gates applied here:
      1. label adjudication — same arxiv_id: highest-priority layer wins
      2. live suspect filter — paper currently suspect is dropped (pool kept;
         clean papers stay usable, verdicts are reversible)
    Output rows carry audit-compatible keys (arxiv_id/adopted) + hub_score/
    degree features (when known) + pool weight for future weighted training.
    """
    pool = pool or default_pool_path()
    rows = _load_rows(pool)

    # Adjudicate: per arxiv_id keep the highest-priority layer row.
    best: dict[str, dict] = {}
    for r in rows:
        layer = r["layer"]
        prio = _LAYER_ORDER.index(layer) if layer in _LAYER_ORDER else 99
        cur = best.get(r["arxiv_id"])
        if cur is None or prio < _LAYER_ORDER.index(cur["layer"]):
            best[r["arxiv_id"]] = r

    # Live suspect filter (needs store statuses).
    out = []
    suspect_aids: set[str] = set()
    if store:
        for p in store.get_all_papers():
            if not p.suspect:
                continue
            for ident in store.get_identifiers(p.sf_id):
                if ident.id_type == "arxiv":
                    suspect_aids.add(ident.id_value)
    for r in best.values():
        aid = r["arxiv_id"]
        if aid in suspect_aids:
            continue  # live gate — do not train on currently-suspect papers
        feat = r.get("features") or {}
        out.append({
            "arxiv_id": aid,
            "adopted": bool(r["label"] == 1),
            "layer": r["layer"],
            "weight": r.get("weight", LAYER_WEIGHT.get(r["layer"], 1.0)),
            "hub_score": feat.get("hub_score"),
            "degree": feat.get("degree"),
        })
    return out
