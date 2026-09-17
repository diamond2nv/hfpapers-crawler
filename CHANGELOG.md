# Changelog — version-line summary

> **This file is the line-level summary** (what each `0.x` line set out to do and what it
> delivered), so the root of the repository answers "how did this evolve?" in one screen.
>
> Detailed per-release entries live in [`docs/CHANGELOG.md`](docs/CHANGELOG.md) — a bounded rolling
> window — with older entries in [`docs/CHANGELOG-archive.md`](docs/CHANGELOG-archive.md). Full
> history, including every commit, is in git (`git log`). English only, like the rest of the
> changelog surface.

## How to read the coverage

Per-release entries begin at **v0.9.13**. Lines before that (v0.2–v0.9) are summarised below from
the commit history and their tags — treat those rows as reconstructed, not contemporaneous prose.
Releases are gated: `scripts/release.sh` refuses a version with no changelog entry, an over-budget
window, or a lost entry (`tests/test_gates.py::TestChangelogGate` / `TestChangelogWindowGate`).

## Version lines

| Line | Period | Theme | Delivered |
|:--|:--|:--|:--|
| **0.2–0.3** | 2026-05 | First working store | Paper pipeline + SQLite `paper_store`, cross-validation audit and audit CLI, Kaggle metadata ingestion, `store export`, PyPI install verified end-to-end, test isolation fixed (62/62) |
| **0.4** | 2026-05 | Publishable project | Robust Kaggle download with DB schema migration, English-only docs (README + code), distributed deployment guide, PEP 8 / PyPI release standards in `AGENTS.md` |
| **0.5.0** | 2026-05 | Open-access sources | CNS open-access searchers (Europe PMC + Semantic Scholar), download-queue prioritisation, graceful Ctrl+C, async downloader error capture |
| **0.6.x** | 2026-06 | Known-id import | `hfpclawer import --arxiv-id` atomic command (resolve → dedup → 3-level PDF fallback → convert → store), design review for the fusion roadmap, `PLAN.md` / `ROADMAP.md`, a starlette/fastapi CVE upgrade |
| **0.7.x** | 2026-06 | Formula verification | `FormulaRegistry` + L1→L5 verification pipeline (SymPy → numeric → dimensional → physical limits → singularities), `hfpclawer verify` |
| **0.8.x** | 2026-07 | Citation traceability | Unified citation-traceability audit engine, generated reports with a verification-layer appendix, `verify report`, the `0.x.y` version convention |
| **0.9.x** | 2026-07 | Zero-LLM tooling | `convert-tex` (arXiv tar.gz → formula-preserving Markdown, 0 LLM), `cron` CLI + cron-verify audit + no_agent script, `ensure_paper` audit trail (`skip_crossref`, `imported_via`), spaCy NLP subpackage |
| **0.10.x** | 2026-07 | Knowledge graph | Graph layer (build / stats / export, JSONL exchange protocol), `graph analyze` + citation visualisation, CLI `person` / `community` / `path`, `wiki/people` YAML frontmatter |
| **0.11.x** | 2026-07 | Citation stepping | Config-driven multi-layer Semantic Scholar walk with DOI/ORCID seeds, keyword/author filters, resume markers, `step` CLI |
| **0.12.x** | 2026-07 | Graph robustness | Graph id bottleneck fixed, ORCID `max_works` + v3 response parsing, stepping continuation from a cached graph, S2 exponential backoff |
| **0.13.x** | 2026-07 | Operations | Cron output normalised, pre-push hook introduced, version/commit-message rules added to `AGENTS.md` |
| **0.14.x** | 2026-07 | More source shapes | Multi-source document adapters; GitHub / DeepWiki ingestion |
| **0.15.0** | 2026-07 | Going public | Internal-plan separation, `hfpclawer-formula-verify` skill, pyright configuration, CLI fixes, and the first self-contained verification gates (B10/B11/C01/C02/F01/F02) |
| **0.15.1–0.15.3** | 2026-08→09 | Fixes + discovery | Nested `data/data/` trap, importer metadata corruption (title = arXiv id, year = 0), hub-guided layered graph expansion (SimClusters-inspired) |
| **0.16.x** | 2026-09 | State, signals, transport | Verification status machine (`pending → verified / stale / suspect`), learned re-ranking (L1, opt-in), SimClusters 2-hop community expansion, pydantic contract boundary, run ledger + `check-new` 0-token gate, repo-scoped profiles and `recommend`, positive-example pool, Zotero sync-back, adversarial audit round, CN-aware transport (TCP → QUIC → browser-hint) with resumable transfers and sha256 audit |
| **0.17.x** | 2026-09 | Public line | The sanitised public line (`public` → GitHub) with its own version sequence: query-string fix in the HTTP/3 `:path`, de-identification recut, transport documentation |
| **0.18.x** | 2026-09 | Sources + governance | Europe PMC / bioRxiv / medRxiv behind one source registry, dedup keys that keep DOI-only records, config-key and venue fixes, `config.local.yaml` overlay for private data, shared retry policy, sanitization gate with version-number guard, sanitized push gate + scripted public release, changelog coverage/window gates, doc-surface audit, README/detail restructure |

## Release rules in force

- `pyproject.toml` is the single version source; the public line is versioned independently.
- A release is blocked without: a changelog entry for that version, a changelog window inside its
  byte budget, and no entry missing from live + archive.
- Push order is tag first, then branch; `scripts/pre-push` checks version/tag consistency on `main`
  and scans every push for sensitive tokens.
- PyPI carries `0.x.0` releases with odd `x` only (`0.17.0` is the latest published); fix releases on
  the even lines stay GitHub/NAS-only.
