# Features

> The five capabilities that define this project, in one screen. [`README.md`](../README.md) keeps
> the five-point summary; this file keeps the detail and links to the reference docs.

## 1. Discovery

- **Multi-source registry** — arXiv API, OpenReview, Papers-with-Code, HuggingFace Papers, and the biomedical adapters (Europe PMC, bioRxiv/medRxiv) all implement one two-member contract (`PaperSource`: `name` + `search`) and register in a single table, `SOURCE_CLASSES`.
- **Community-guided expansion** — `hfpclawer graph expand-hub --community` walks seed → its Louvain communities → community hubs, a faithful mapping of the x-algorithm SimClusters idea, for topic-focused "papers like this one" exploration.
- **Relevance scoring and dedup that keeps data** — keyword classification plus cross-source dedup keyed on `arxiv_id → doi → title`; records without any usable key are kept, not dropped.

Details: [`docs/USAGE.md`](USAGE.md) · [`docs/ARCHITECTURE.md`](ARCHITECTURE.md)

## 2. Verification

- **Explicit status machine** — every paper carries `pending → verified / stale / suspect`, derived from stored evidence rather than from an LLM's opinion.
- **Conflicts become visible** — a DOI resolving to a different arXiv id than recorded marks the paper **suspect**; suspect records never count as verified and never enter the training pool.
- **Symbolic, 0-LLM checks** — the checks are deterministic; no LLM is asked to judge whether a paper is real.

Details: [`docs/paper_store.md`](paper_store.md) · [`docs/use/verify-guide.md`](use/verify-guide.md)

## 3. Recommendations

- **First-party signals** — search history × text similarity × relevance × verification gating, computed from the local store; no external service required, nothing to sign up for.
- **Repo-scoped profiles** — every repo is its own virtual user: `hfpclawer init` scaffolds `REPO_USER.md`, whose v2 `accepts/rejects` blocks act as explicit feedback (with `scope: topic-exclusion` filtering candidates and `scope: self-constraint` documenting choices without filtering).
- **Learned layer is opt-in and explainable** — `hfpclawer rank train` (lightgbm → native model) learns from JSONL audit trails with feature importance as the explanation; the heuristic layer stays the 0-token default.
- **Auditable trails and a clean pool** — every expansion can emit an audit trail, and `hfpclawer pool` accumulates layered weak labels from local, label-free sources; append-only and gitignored, so no telemetry leaves the machine.
- **Zotero, optional** — `hfpclawer zotero sync-back` pulls Favor-tagged items through the scholarly contract (web pages and reports are dropped first) and marks matching papers `favorited`; Zotero absent changes nothing.

Details: [`README.md`](../README.md) · [`docs/ROADMAP.md`](ROADMAP.md)

## 4. Configuration and sources

- **Public config is publishable** — the tracked `config.yaml` contains structure and placeholders only; real names, ORCIDs and query lists live in the gitignored `config.local.yaml`, deep-merged over it (`search.biomed_queries: []` is the declared slot).
- **Registration is not enablement** — an adapter runs only when its key is in `search.enabled`; adding a source can never change existing behaviour.
- **Field shapes verified before implementation** — Europe PMC needs `resultType=core` or abstracts arrive empty; bioRxiv/medRxiv expose a date-range API only, so keyword filtering happens at ingest.
- **Shared retry policy** — all sources call through `PaperSource._get()`, honouring `anti_crawl.max_retries` / `retry_http_codes` / `retry_delay_base`; one transient 503 no longer drops a batch.

Details: [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) · [`DEPLOY.md`](../DEPLOY.md)

## 5. Agent-first

- **CLI-first, MCP second** — every capability is a documented subcommand with machine-checkable output; the MCP server exposes the read-only core by default and hides heavy operations to save tokens.
- **0-token monitoring** — `hfpclawer check-new` compared against its own previous output is the cron gate: stable output means "nothing changed, do not wake the LLM".
- **Transport that survives a hostile network** — TCP → QUIC → browser-hint ladder, resumable transfers, and a sha256 per fetch recorded in `data/download_audit.jsonl`.
- **Gates, not discipline** — `scripts/pre-push` refuses un-sanitized commits and version/tag mismatches; `scripts/release.sh` refuses a release whose changelog lacks the entry, exceeds its byte window, or lost an entry; `scripts/doc_audit.py` checks that documented paths and commands exist.

Details: [`AGENTS.md`](../AGENTS.md) · [`docs/DEVELOPMENT.md`](DEVELOPMENT.md) · [`docs/CHANGELOG.md`](CHANGELOG.md)

## What is deliberately not here

- Cloud sync / hosted storage (the store is local, single-point data); paper notes and annotations (the wiki layer); L6 formal verification (interface reserved only). See [`ROADMAP.md`](../ROADMAP.md).
