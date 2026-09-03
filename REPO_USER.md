# REPO_USER.md — hfpapers-crawler interest profile (hfpclawer recommendations)

> This repo's VIRTUAL-USER picture: hfpclawer is developed HERE, so its own
> profile declares which research directions this repo consumes/adopts and
> which it has deliberately rejected (see docs/ROADMAP.md 拒绝清单).
> Only `active` declarations are consumed (SKILL.state); superseded/revoked
> entries stay for audit. Public-repo safe: neutral academic keywords only.

```yaml
hfpclawer:
  schema: 2
  profile: hfpclawer-scholarly-recommendation
  queries:
    - query: "recommendation system citation network"
      weight: 3
    - query: "collaborative filtering graph embedding"
      weight: 2
    - query: "scholarly metadata verification"
      weight: 2
  categories: [recommendation, scholarly-graph, metadata-verification]
  from_wiki: concepts/xai-x-algorithm-recommendation-2026

  accepts:            # methods this repo adopts (code-level: pyproject.toml deps)
    - type: method
      state: active
      name: lightgbm
      keywords: [lightgbm, gradient boosting]
      since: "2026-09-03"
      evidence: {file: "pyproject.toml", lines: []}
    - type: method
      state: active
      name: simclusters-community-2hop
      keywords: [simclusters, community detection, louvain]
      since: "2026-09-03"
      evidence: {file: "docs/ROADMAP.md", lines: [475]}
    - type: method
      state: active
      name: contract-boundary-pydantic
      keywords: [pydantic, contract boundary]
      since: "2026-09-03"
      evidence: {file: "docs/ROADMAP.md", lines: [475]}

  rejects:            # methods deliberately NOT consumed here (ROADMAP 拒绝清单)
    - type: method
      state: active
      version: 1
      name: online-learning
      keywords: [online learning, incremental learning, online recommender, lifelong learning]
      since: "2026-09-03"
      reasons: "no behavior-data scale — full retrain per run is enough (§2d/§2e)"
      evidence: {file: "docs/ROADMAP.md", lines: [354]}
    - type: method
      state: active
      version: 1
      name: collaborative-filtering
      keywords: [collaborative filtering, matrix factorization, user-item, implicit feedback]
      since: "2026-09-03"
      reasons: "no user-item interaction data at this scale (§2e) — would be spurious signal"
      evidence: {file: "docs/ROADMAP.md", lines: [354]}
    - type: method
      state: active
      version: 1
      name: federated-telemetry
      keywords: [federated learning, telemetry, user tracking]
      since: "2026-09-03"
      reasons: "open-source zero-telemetry discipline (§2e)"
      evidence: {file: "docs/ROADMAP.md", lines: [534]}
```
