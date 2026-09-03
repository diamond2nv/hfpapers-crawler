## [2026-06-12] feat | v0.10.2 — wiki/people YAML frontmatter, smart name search, TOPIC injection from title, graph config
- **M** `hfpapers/graph/sources/wiki.py` — Rewritten: YAML frontmatter + H1 header `# 人物卡片：Name（Pinyin）` parsing, table-based ORCID/affiliation extraction, markdown link ORCID cleaning
- **M** `hfpclawer/graph_cli.py` — `cmd_person()`: smart name resolution (full name, "Last, First", fuzzy fallback with suggestions), Chinese name support
- **A** `config.yaml` — `graph:` section: wiki_dir, cache_path, topic_from_title, skip_common_phrases
- **M** `hfpapers/graph/__init__.py` — GraphBuilder reads `config.yaml` graph section; TOPIC nodes auto-injected from paper titles (`_topic_from_title()` → `ABOUT_TOPIC` edges); `_load_config()` fallback
- **M** `wiki/people/*.md` (11 files) — Added YAML frontmatter: name (Last, First), orcid (verified via ORCID API), affiliation, research_interests
- **A** `config.yaml§graph` — `graph:` section with wiki_dir, cache_path, topic_from_title, skip_common_phrases

## [2026-06-12] feat | v0.10.1 — graph: persist, analyze, CLI person/community/path
- **A** `hfpapers/graph/analyze.py` — Centrality (degree/betweenness/PageRank), Louvain communities, ego network, shortest path. PageRank falls back to degree centrality when scipy unavailable
- **M** `hfpapers/graph/__init__.py` — Graph pickle persistence (`save()`/`load()`), auto-cache after build. Dead code cleanup (`_person_authority_map` removed). Fix: `_add_node` double `label` keyword crash
- **M** `hfpclawer/graph_cli.py` — `cmd_person()`, `cmd_community()`, `cmd_path()` with Rich output. Cache-first loading for stats/export
- **M** `hfpapers/cli.py` — `graph` command extended with `person`, `community`, `path` actions

## [2026-06-12] feat | v0.10.0 — knowledge graph layer
- **A** `hfpapers/graph/` — Graph module: schema (NodeType/EdgeType, PERSON/PAPER/BOOK/JOURNAL/TOPIC), sources (Zotero items → nodes/edges with innovation_tags, wiki/people/ → PERSON ground truth), GraphBuilder with stats/export (JSONL for hedge, GraphML for Gephi)
- **A** `hfpclawer/graph_cli.py` — CLI: `hfpclawer graph {build, stats, export}`

# CHANGELOG

## [2026-09-03] feat | v0.16.3 — pydantic contract boundary: ZoteroItem model
- **A** `hfpapers/contracts.py` — Pydantic contract models at API/JSON boundaries only (mechanical layer stays plain-dict): `ZoteroItem` encodes the scholarly-item filter discipline (roadmap §2b) as a single source of truth — `scholarly` ⇔ carries a DOI or an arXiv ID (itemType whitelist is only a fast path; Zotero type fields unreliable for preprint-shaped items). `paper_identifier` → ("arxiv"|"doi", id) for paper_store matching. Handles `DOI`-cased JSON keys, `doi:`/`arXiv:` prefixes, archiveID extraction.
- **A** `pyproject.toml` — `pydantic>=2.7` moved to core dependencies.
- **A** `tests/test_contracts.py` — 8 tests: DOI/arXiv scholarly paths, prefix stripping, non-scholarly rejection (book/webpage/report), Zotero JSON surface aliases, Extra-field false-positive guard, required key.

## [2026-09-03] feat | v0.16.2 — SimClusters community-guided 2-hop expansion
- **A** `hfpapers/graph/citation_expander.py` — `HubGuidedExpander.community_guided_run()`: faithful x-algorithm SimClusters mapping onto the citation graph — seed paper (user) → its Louvain communities (clusters) → community hub papers (producers). Frontier stays topic-focused (candidates must share the seed's community), unlike the plain global PageRank+degree hub run. Audit rows carry the `community` feature for the L1 ranker.
- **M** `hfpapers/graph/citation_expander.py` — docstrings made honest: `run()` = per-layer ranking/truncation *inspired by* SimClusters diffusion control; `community_guided_run()` = faithful 2-hop. Previous "SimClusters inspired" claim on the heuristic-only mode removed.
- **A** `hfpapers/graph/__init__.py` — `expand_hub_guided()` gained `audit_path` + `community_guided` passthrough.
- **M** `hfpclawer/graph_cli.py` + `hfpapers/cli.py` — `graph expand-hub` gained `--audit <path>` (rank-training JSONL trail) and `--community` (SimClusters 2-hop mode); layer output shows communities/candidates in community mode.
- **A** `tests/test_simclusters.py` — 3 tests: structural frontier⊆seed-community guarantee, audit-community compatibility with the L1 ranker, all-candidates-share-seed-community. (Assertions are structural — real Louvain produces bridge communities; perfect cluster splits are not assumed.)

## [2026-09-03] feat | v0.16.1 — learned re-ranking layer (L1) on hub audit trails
- **A** `hfpapers/rank.py` — lightgbm training on HubGuidedExpander audit JSONL: positive = papers the hub heuristic adopted into the next frontier; negative = candidates truncated at the same layer. Features: hub_score/degree/layer. Tree feature importance doubles as the audit ("why was this ranked"). Native lightgbm model artifact (no fake ONNX — real conversion needs lgbm2onnx, deliberately out of core deps). `importorskip`-guarded, optional `hfpclawer[rank]` extra.
- **A** `hfpapers/graph/citation_expander.py` — `run()` gained `audit_path`: per-candidate JSONL trail (arxiv_id/adopted/hub_score/degree/layer/source), single-pass score map (no per-candidate pagerank recompute).
- **A** `hfpapers/cli.py` — `hfpclawer rank train --audit <path> --out <model>` with feature-importance audit output.
- **A** `pyproject.toml` — extras `rank = [lightgbm, scikit-learn, onnxruntime]`, `rank-gpu = [hfpclawer[rank], torch]`.
- **A** `tests/test_rank.py` — 5 tests: load/build shapes, learns adopted-vs-truncated pattern (good scores above bad), too-small/empty datasets raise.

## [2026-09-03] feat | v0.16.0 — state semantics + verification status machine
- **A** `hfpapers/paper_store.py` — Migration v3: `suspect` / `suspect_at` columns. Explicit first-class abstain state (SKILL.state semantics): suspect ≠ "unaudited" — audit conflicts are visible and require human adjudication.
- **A** `hfpapers/paper_store.py` — State semantics API: `mark_suspect()` / `clear_suspect()` / `get_status()` / `status_summary()` — derived status machine `pending → verified / stale / suspect` (hard predicates over audit_level + timestamps; symbolic verdicts, never LLM-judged). Stale = verified but older than stale_days (default 180).
- **A** `hfpapers/paper_store.py` — `detect_identifier_conflicts()`: cross-source conflict detection (DOI via crossref_cache resolving to a different arXiv ID than recorded) — 0-LLM symbolic SQL.
- **A** `hfpapers/cli.py` — `store` actions: `status` (per-paper or summary table), `conflicts` (identifier conflict list), `suspect <aid> "<reason>"`, `clear-suspect <aid>`.
- **A** `tests/test_state.py` — 9 tests: migration idempotency, pending/verified/suspect/stale derivation, suspect-first-class override, conflict detection + resolution, verify_paper regression.
- **Design note** — Recommendation-signal robustness (roadmap §2b): signals are first-party local (search.queries × text similarity + relevance + verification status gate); Zotero is an optional enhancement adapter, never a hard dependency. Filtering discipline: only DOI/arXiv-bearing scholarly items sync back.

## [2026-08-16] feat | v0.15.3 — hub-guided layered graph expansion (SimClusters inspired)
- **A** `hfpapers/graph/citation_expander.py` — HubGuidedExpander class + _hub_scores (PageRank+degree); layered expansion with frontier truncation, per-layer checkpoint resume
- **A** `hfpapers/cli.py` — `hfpclawer graph expand-hub [seeds] [layers]` (--top N, --source checkpoint)
- **A** tests — 4 new (hub scoring, source filter, checkpoint resume, empty frontier)

## [2026-08-10] fix | v0.15.2 — importer metadata corruption (title=arXiv ID, year=0)
- **F** `hfpclawer/import_paper/importer.py` — `_fetch_arxiv_meta()` parsed title/abstract from arXiv API but **never assigned them back** (only appended to `result.steps` log). `import_arxiv_id()` then fell back to `title=title or arxiv_id`, writing garbage records like `title="2504.19413", year=0` into paper_store. Now populates `result.title` / `result.abstract` / `result.year` (from `<published>`), and Step 5 uses `title or result.title or arxiv_id`.
- **F** `hfpclawer/import_paper/importer.py` — DOI branch: `ensure_paper()` now receives `doi=` when `resolved.source == "doi"` (previously DOI string was passed as arXiv ID).
- **F** `hfpclawer/import_paper/importer.py` — year backfill: after store write, if arXiv metadata had a year and the new record's year is 0, backfill via `get_store().upsert_paper()` (ensure_paper has no year param).
- **A** `tests/test_import.py` — `TestFetchArxivMeta` regression tests (mock arXiv Atom XML): title/abstract/year assigned on success; empty meta on API failure (best-effort, non-fatal).

## [2026-08-10] fix | v0.15.1 — nested data/data/papers.db trap
- **F** `hfpapers/paper_store.py` — `_db_path()` resolves relative `paths.data_dir` against **package root** (`Path(__file__).parent.parent`), not `os.getcwd()`. Previously running the CLI from inside `data/` created a nested empty `data/data/papers.db` while PDF/MD went to the real dir — metadata silently lost.
- **A** `tests/test_paper_store.py` — regression tests for `_db_path()` resolution under different CWDs.

> Append-only changelog for hfpapers-crawler. English only (PEP8 internationalization).

## [2026-05-20] feat | hfpclawer-academic-integrity Hermes skill
- **A** `skills/hfpclawer-academic-integrity/SKILL.md` — Hermes Agent skill: paper draft integrity audit. Extracts citations, runs L1→L2→L3→L4 cascade, flags FABRICATED references, generates structured report with recommendations (8108B, 207 lines)

## [2026-05-20] infra | bulk maintenance: AGENTS.md, README, docs, citation_audit.py, Hermes skills
- **A** `hfpclawer/citation_audit.py` — Citation audit engine Phase 1 (L1 FTS5 existence check). CLI modes: `--check`, `--arxiv-id`, `--refs`
- **A** `skills/hfpclawer-paper-search/SKILL.md` — Hermes Agent skill: daily paper search→download→convert→wiki workflow (6782B, 232 lines)
- **A** `skills/hfpclawer-citation-audit/SKILL.md` — Hermes Agent skill: citation audit (local FTS5→S2→OpenAlex) for researchers (6722B, 183 lines)
- **A** `docs/kaggle-metadata.md` + `docs/cn/kaggle-metadata.zh-CN.md` — Kaggle JSONL + OAI-PMH deployment guide (Kaggle CLI install, API token config, ~5.3GB/11GB storage warning, manual `git clone` instructions for PyPI limitation)
- **M** `AGENTS.md` — Backported 2 practices from expflow: (1) Config Cache global singleton test reset; (2) Graceful Degradation 6 rules (BrokenPipeError MCP handler, KeyboardInterrupt top-level catch)
- **M** `README.md` — `[arxiv]` dependency points to public GitHub (was private GitLab), PyPI `git+https` limitation noted; added `[audit]` optional dep
- **M** `docs/cn/README.zh-CN.md` — Synced English changes
- **M** `pyproject.toml` — `[arxiv]` and `[audit]` removed `git+https` deps (PyPI incompatible), replaced with comment-only placeholders
- **M** `docs/NETWORK.md` + `docs/cn/NETWORK.zh-CN.md` — GitLab entry → GitHub

## [2026-07-12] feat | cron CLI + cron-verify audit + no_agent script
- **A** `hfpclawer/audit/cron_verify.py` — Batch Crossref verify + retraction check module for cron-imported papers (VerifyStats dataclass, batch_verify(), format_report(), format_report_json())
- **A** `hfpclawer/cli_cron.py` — `hfpclawer cron {init,check,run,import}` CLI subcommands (3-tier DB path resolution, arXiv API search, paper_store import with skip_crossref=True, config.yaml generation)
- **A** `scripts/hfpclawer-cron-fetch.sh` — no_agent mode shell script (0 LLM token, --json/--help modes, auto venv detection)
- **A** `docs/cron-guide.md` + `docs/cn/cron-guide.zh-CN.md` — Bilingual user guide (quickstart, commands, DB path, verification pipeline)
- **M** `hfpapers/cli.py` — Register `cron` command + `audit cron-verify` action in ACTION_DESCRIPTIONS

## [2026-07-12] feat | spaCy NLP subpackage (v0.9.13)
- **A** `hfpapers/nlp/` — 6-module NLP subpackage: keywords (lemmatization), search (vector reranking), innovation (5-7 point extraction), tags (auto-tag generation), tag_analysis (TF-IDF library scan)
- **M** `hfpclawer/zotero/__init__.py` — Wire spaCy into `_title_keywords`; L1b semantic rerank; `update_item_extra()`
- **M** `hfpclawer/zotero/cli.py` — `cmd_innovate`, `cmd_tag_report`
- **M** `hfpapers/cli.py` — Wire `innovate` and `tag-report` actions
- **M** `pyproject.toml` — `[nlp]` and `[nlp-full]` optional deps

## [2026-07-12] docs | Knowledge Graph v0.10.x roadmap + plan
- **A** `docs/ROADMAP.md` — v0.10.x knowledge graph roadmap
- **A** `docs/plans/knowledge-graph-v0.10.md` — Detailed implementation plan (~1600 lines, 7 node types, 7 edge types)
- **M** `AGENTS.md` — Add Environment and Connectivity section