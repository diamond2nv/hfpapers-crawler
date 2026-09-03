#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ledger.py — run-level accounting (HL-ledger style, roadmap §2c).

Each operation appends one JSONL row to data/ledger.jsonl:
  timestamp / event / source / sf_id_delta / llm_cost / next_hypothesis

Cost discipline (roadmap §2c — three sources, never guessed):
  L1 usage-direct: caller passes real llm_cost from an API usage response
     (prompt+completion tokens × config unit price) — the ONLY precise source.
  L2 hermes attribution / L3 balance reconciliation live OUTSIDE this repo
     (Hermes OTel/langfuse + llm-api-balance-check) — ledger keeps meta links.

Mechanical layer: plain-dict append (no pydantic; contracts live at API
boundaries only). Deterministic, append-only, 0-LLM.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

LEDGER_NAME = "ledger.jsonl"


def ledger_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / LEDGER_NAME


def log(
    data_dir: str | Path,
    event: str,
    source: str = "",
    sf_id_delta: int = 0,
    llm_cost: float = 0.0,
    next_hypothesis: str = "",
    meta: dict | None = None,
) -> dict:
    """Append one ledger row. Returns the row (also written to disk)."""
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        "source": source,
        "sf_id_delta": int(sf_id_delta),
        "llm_cost": round(float(llm_cost or 0.0), 6),
        "next_hypothesis": next_hypothesis,
    }
    if meta:
        row["meta"] = meta
    path = ledger_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def recent(data_dir: str | Path, limit: int = 20) -> list[dict]:
    """Last N rows (newest first)."""
    path = ledger_path(data_dir)
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # defensive: skip corrupt trailing writes
    return rows[-limit:][::-1]


def stats(data_dir: str | Path, since_days: int = 30) -> dict:
    """Aggregate: rows by event, sf_id deltas, llm cost (last N days)."""
    path = ledger_path(data_dir)
    counts: dict[str, int] = {}
    sf_delta = 0
    cost = 0.0
    n = 0
    cutoff = datetime.now() - timedelta(days=since_days)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = row.get("timestamp", "")
                if ts:
                    try:
                        if datetime.fromisoformat(ts) < cutoff:
                            continue
                    except ValueError:
                        pass
                counts[row.get("event", "?")] = counts.get(row.get("event", "?"), 0) + 1
                sf_delta += int(row.get("sf_id_delta", 0) or 0)
                cost += float(row.get("llm_cost", 0.0) or 0.0)
                n += 1
    return {"rows": n, "by_event": counts, "sf_id_delta": sf_delta,
            "llm_cost_total": round(cost, 6), "since_days": since_days}


# ─── check-new: 0-token change detection (cron monitor layer 1) ──────────────

_STATE_NAME = "check_new_state.json"


def _state_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / _STATE_NAME


def check_new(store, data_dir: str | Path, since_minutes: int = 0) -> dict:
    """0-LLM store-level change detection.

    Compares the current paper count / newest created_at against the last
    check (persisted to data/check_new_state.json). Identical output when
    nothing changed → safe for a cron monitor gate (0-token skip).

    Returns {new_papers, total, last_check, first_new_id, window}.
    """
    with store._conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        newest = conn.execute(
            "SELECT sf_id, created_at FROM papers ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

    state_path = _state_path(data_dir)
    prev_total = 0
    prev_ts = ""
    if state_path.exists():
        try:
            st = json.loads(state_path.read_text())
            prev_total = int(st.get("total", 0))
            prev_ts = st.get("checked_at", "")
        except (OSError, ValueError):
            pass

    new_papers = max(0, total - prev_total)
    row = {
        "total": total,
        "new_papers": new_papers,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "first_new_id": int(newest["sf_id"]) if newest else None,
        "prev_total": prev_total,
        "prev_checked_at": prev_ts,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(row))
    return row
