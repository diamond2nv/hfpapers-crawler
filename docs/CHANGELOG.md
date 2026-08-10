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