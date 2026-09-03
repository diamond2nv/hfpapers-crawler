"""ProfileVerdict declaration tests (REPO_USER.md v2 — accept/reject state machine)."""


from hfpapers.paper_store import PaperStore
from hfpapers.profile import (
    RepoProfile,
    parse_agents_profile,
)
from hfpapers.recommend import _hits_reject, recommend

V2_BLOCK = """# REPO_USER.md — demo

```yaml
hfpclawer:
  schema: 2
  profile: demo-rec
  queries:
    - query: "graph learning"
      weight: 2
  accepts:
    - type: method
      state: active
      name: lightgbm
      keywords: [lightgbm, gradient boosting]
      since: "2026-09-01"
      evidence: {file: "docs/ROADMAP.md", lines: [456]}
    - type: paper
      state: active
      identifiers: {arxiv: "2502.17416", doi: "10.48550/arXiv.2502.17416"}
    - type: method
      state: superseded   # history kept, not consumed
      name: old-approach
  rejects:
    - type: method
      state: active
      name: online-learning
      keywords: [online learning, incremental learning, bandit]
      reasons: "pool is small — full retrain per run is enough"
      evidence: {file: "docs/ROADMAP.md", lines: [354]}
    - type: paper
      state: revoked       # revoked → inert
      identifiers: {arxiv: "2501.00001"}
```
"""


def _write_profile(tmp_path, text):
    p = tmp_path / "REPO_USER.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_v2_block_parses_accepts_rejects(tmp_path):
    _write_profile(tmp_path, V2_BLOCK)
    prof = parse_agents_profile(tmp_path / "REPO_USER.md")
    assert prof.profile == "demo-rec"
    # accepts: 2 active (lightgbm method + paper) + 1 superseded
    assert len(prof.accepts) == 3
    # rejects: 1 active method + 1 revoked paper
    assert len(prof.rejects) == 2


def test_only_active_consumed(tmp_path):
    _write_profile(tmp_path, V2_BLOCK)
    prof = parse_agents_profile(tmp_path / "REPO_USER.md")
    active = prof.active_verdicts()
    assert all(v.state == "active" for v in active)
    # superseded accept and revoked reject are NOT consumed
    names = [(v.verdict, v.name or list(v.identifiers.values())[0]) for v in active]
    assert ("accept", "lightgbm") in names
    assert ("reject", "online-learning") in names
    assert all(name != "old-approach" for _, name in names)
    assert all(name != "2501.00001" for _, name in names)


def test_reject_keywords_vocabulary(tmp_path):
    _write_profile(tmp_path, V2_BLOCK)
    prof = parse_agents_profile(tmp_path / "REPO_USER.md")
    kws = prof.reject_keywords()
    assert "online learning" in kws
    assert "incremental learning" in kws
    assert "bandit" in kws


def test_placeholder_keywords_never_filter(tmp_path):
    text = V2_BLOCK.replace(
        'keywords: [online learning, incremental learning, bandit]',
        'keywords: ["<keyword-a>", "<keyword-b>"]',
    )
    _write_profile(tmp_path, text)
    prof = parse_agents_profile(tmp_path / "REPO_USER.md")
    assert prof.reject_keywords() == []  # templates inert


def test_paper_verdict_identifiers(tmp_path):
    _write_profile(tmp_path, V2_BLOCK)
    prof = parse_agents_profile(tmp_path / "REPO_USER.md")
    paper_accept = [v for v in prof.accepts if v.type == "paper"][0]
    assert paper_accept.identifiers["arxiv"] == "2502.17416"
    assert paper_accept.identifiers["doi"] == "10.48550/arXiv.2502.17416"


def test_evidence_anchor(tmp_path):
    _write_profile(tmp_path, V2_BLOCK)
    prof = parse_agents_profile(tmp_path / "REPO_USER.md")
    reject = [v for v in prof.rejects if v.type == "method"][0]
    assert reject.evidence == {"file": "docs/ROADMAP.md", "lines": [354]}
    assert reject.reasons  # why = audit trail


def test_self_constraint_scope_never_filters(tmp_path, monkeypatch):
    """scope=self-constraint documents OUR choice — must NOT gate papers.

    Regression for the 2026-09-03 audit: "WE don't use telemetry" used to
    hard-filter papers ABOUT telemetry (category error).
    """
    import hfpapers.recommend as mod

    store = PaperStore(db_path=str(tmp_path / "t.db"))
    with store._lock, store._conn() as conn:
        cur = conn.execute(
            "INSERT INTO papers (title, abstract) VALUES (?, ?)",
            ("Federated Learning for Scholarly Discovery", "telemetry protocols"),
        )
        sf = cur.lastrowid
    text = """# R

```yaml
hfpclawer:
  profile: x
  queries:
    - query: "scholarly discovery"
      weight: 2
  rejects:
    - type: method
      state: active
      name: telemetry
      scope: self-constraint   # we don't telemetry — irrelevant to papers
      keywords: [telemetry, federated learning]
```
"""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "REPO_USER.md").write_text(text, encoding="utf-8")

    monkeypatch.setattr(mod, "_config_queries", lambda: [])
    monkeypatch.setattr(mod, "user_profile", lambda: RepoProfile())
    results = mod.recommend(store, limit=10, repo_dir=str(repo_dir))
    ids = {r["sf_id"] for r in results}
    assert sf in ids  # self-constraint must NOT exclude the paper

    # topic-exclusion WOULD exclude it (gate vocabulary difference)
    text2 = text.replace("scope: self-constraint", "scope: topic-exclusion")
    (repo_dir / "REPO_USER.md").write_text(text2, encoding="utf-8")
    results2 = mod.recommend(store, limit=10, repo_dir=str(repo_dir))
    assert sf not in {r["sf_id"] for r in results2}


def test_stale_human_vetted_exempt_from_penalty(tmp_path, monkeypatch):
    """audit_level>=2 stale papers keep full weight (classics not buried)."""
    import hfpapers.recommend as mod

    store = PaperStore(db_path=str(tmp_path / "t.db"))
    old = "2025-01-01 00:00:00"  # >180 days stale
    with store._lock, store._conn() as conn:
        # stale + human-vetted (audit_level=2)
        cur = conn.execute(
            "INSERT INTO papers (title, abstract, audit_level, audit_level_at) "
            "VALUES (?, ?, 2, ?)",
            ("Foundational Deep Operator Paper", "neural operator theory", old),
        )
        sf_vetted = cur.lastrowid
        # stale + metadata-only (audit_level=1) → should be penalized
        cur = conn.execute(
            "INSERT INTO papers (title, abstract, audit_level, audit_level_at) "
            "VALUES (?, ?, 1, ?)",
            ("Old Metadata Paper", "neural operator survey", old),
        )
        sf_plain = cur.lastrowid

    monkeypatch.setattr(mod, "_config_queries", lambda: [("operator", 1, "global")])
    monkeypatch.setattr(mod, "detect_profile", lambda d: RepoProfile())
    monkeypatch.setattr(mod, "user_profile", lambda: RepoProfile())
    results = mod.recommend(store, limit=10, repo_dir=None, status_gate=True)
    by_id = {r["sf_id"]: r for r in results}
    assert sf_vetted in by_id and sf_plain in by_id
    # both stale from the same age — vetted one must score HIGHER (no penalty)
    assert by_id[sf_vetted]["score"] > by_id[sf_plain]["score"]


def test_hits_reject_matches_title_and_abstract():
    class P:
        title = "Scalable Online Learning Systems"
        abstract = ""

    assert _hits_reject(P(), {"online learning", "bandit"})
    assert not _hits_reject(P(), {"bandit"})  # title has no bandit


def test_recommend_applies_reject_gate(tmp_path, monkeypatch):
    """Papers hitting an active reject keyword never surface."""
    import hfpapers.recommend as mod

    store = PaperStore(db_path=str(tmp_path / "t.db"))
    with store._lock, store._conn() as conn:
        cur = conn.execute(
            "INSERT INTO papers (title, abstract) VALUES (?, ?)",
            ("Online Learning for Recommendation", "bandit methods here"),
        )
        sf_hit = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO papers (title, abstract) VALUES (?, ?)",
            ("Representation Learning for Graph Analysis", "gnn topology"),
        )
        sf_ok = cur.lastrowid
        conn.execute(
            "INSERT INTO identifiers (sf_id, id_type, id_value) VALUES (?, 'arxiv', ?)",
            (sf_hit, "2509.00001"),
        )
        conn.execute(
            "INSERT INTO identifiers (sf_id, id_type, id_value) VALUES (?, 'arxiv', ?)",
            (sf_ok, "2509.00002"),
        )
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "REPO_USER.md").write_text(V2_BLOCK, encoding="utf-8")

    monkeypatch.setattr(mod, "_config_queries", lambda: [("learning", 2, "global")])
    monkeypatch.setattr(mod, "user_profile", lambda: RepoProfile())
    results = recommend(store, limit=10, repo_dir=str(repo_dir))
    ids = {r["sf_id"] for r in results}
    assert sf_hit not in ids  # reject gate: online-learning keyword hit
    assert sf_ok in ids  # unaffected paper surfaces
