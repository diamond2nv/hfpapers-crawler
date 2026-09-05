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

## [2026-09-05] fix | v0.16.14 — sink-path payload validation: file head, not residual tail
> Bugfix for `fetch -k source -t quic` (and any sink-backed large transfer) that
> stalled forever on the .part file although the payload had fully arrived.

- **root cause** — `async_quic_fetch` with `sink=<dest>.part` + `range_from=0`
  streamed the payload head to disk every `flush_every` bytes, so the in-memory
  `protocol.body` only ever held the residual **mid-file tail** (< flush_every,
  no %PDF / gzip magic by construction). The old code ran `_payload_ok()` on
  that tail → false `ok=False` on an otherwise complete transfer.
  `fetch_resumable` then appended the tail and issued a `Range: bytes=<EOF>-`
  resume round — arXiv/Fastly answers 416 or hangs there → **.part stuck at full
  size, never renamed** (2026-09-05 LAN peer measured: 3,947,319-byte tar.gz arrived
  in ~1s but the CLI looped instead of finalising; pdf only survived via the
  416-promote path).
- **fix** — sink path (`range_from == 0 and sink.exists()`) now validates the
  **file on disk**: total size (disk + residual) ≥ `_MIN_BYTES`, then
  kind-specific magic read from the file head (%PDF for pdf; gzip `1f 8b` for
  source, NUL-sampling the flushed region for raw-tex bundles). The in-memory
  tail is no longer magic-checked by construction.
- **tests** — +2 regression tests drive `async_quic_fetch` end-to-end with a
  mocked aioquic connection: source gzip > flush_every and pdf %PDF > flush_every
  both now return `ok=True` while asserting the old tail check would have
  rejected them (`tests/test_arxiv_transport.py`).
- verified: `hfpclawer fetch 2608.06013 -k source -t quic` → complete
  `2608.06013.tar.gz` 3,947,319 B, sha256 a4da7e96…, ~1.1s, tar listing OK.
  28/28 transport tests + 92 core tests pass; ruff clean.
- note: repo `.venv` is uv-managed; use `uv pip install -e . --no-deps
  --python .venv/bin/python` (a session-level `VIRTUAL_ENV` can silently point
  uv at another env).

- **cross-channel verification** — sha256 of a QUIC direct fetch (official
  arXiv) and an AlphaXiv mirror copy are **byte-identical**, confirming the
  QUIC channel end-to-end (reliability test = cross-channel agreement).
  Note: AlphaXiv's real PDFs live at `pdfs.assets.alphaxiv.org` (not the
  main site). Audit hashes for every completed fetch land in
  `data/download_audit.jsonl` — the comparison record for MITM checks.

## [2026-09-03] feat | v0.16.13 — bounded-memory streaming + .part lifecycle
> Memory-peak control and temporary-file hygiene for the QUIC path.

- **incremental flush (sink)** — async_quic_fetch/quic_batch_fetch stream to
  the target file every 512KB via `_flush_body`; peak RAM drops from
  O(file size) to O(512KB × streams) — batch re-fetch of N multi-MB tex
  bundles no longer buffers the whole payload in memory. (aiofiles was
  evaluated and rejected: it is a thread-pool wrapper for blocking writes and
  cannot be awaited inside aioquic's sync event callbacks — a sync short
  append per flush chunk is the right tool here.)
- **connection-close detection** — `connection_lost` now wakes the waiter
  immediately (previously a server close mid-transfer idled until the round
  timeout, wasting up to 90s × rounds); truncated transfers are reported as
  incomplete right away
- **416 promote** — resume round hitting `416 Range Not Satisfiable` means
  the .part already holds the complete body (server closed after delivering
  it): the file is promoted with its sha256 instead of looping (was: infinite
  resume until rounds exhausted)
- **.part lifecycle** — `fetch_resumable` never raises (exceptions wrapped
  into failed FetchResults reporting the surviving .part); stale .part
  (default >24h, `stale_part_after`) is reclaimed before a new transfer;
  `max_bytes` caps the temporary file against runaway payloads; failed sunk
  streams in the batch downloader remove their partial file unconditionally
  (a >5KB partial can no longer masquerade as a completed download)
- tests: +4 (416 promote / stale reclaim / max_bytes abort / exception wrap)
  — 124 offline + 2 live-verified: PDF 2.4MB resume path, 12.7MB killed-
  process .part recovered and promoted (sha recorded, no residue)

## [2026-09-03] feat | v0.16.12 — Range-resumable QUIC + batch re-fetch + file integrity
> Follow-up to v0.16.11: the batch path now uses the unified QUIC connection,
> and interrupted transfers resume instead of restarting from zero.

- **`fetch_resumable` / `file_sha256`** — .part file + `Range: bytes=N-`
  resume loop (verified live: 12.7MB tex bundle that previously stalled at
  1.9MB/90s now completes over resumed rounds); partial bytes survive
  timeouts (async_quic_fetch keeps body on failure); assembled file gets a
  sha256 that is recorded to the acquisition audit (cross-channel compare);
  full-body hash mismatch → file dropped, no false success
- **batch re-fetch via `quic_batch_fetch`** — AsyncPdfDownloader TCP phase
  runs 1 attempt per paper (CN resets are deterministic), then ALL failures
  are re-fetched in ONE QUIC connection with N concurrent streams (amortised
  ramp); per-paper fallback still available on the single-paper path
- `_persist_pdf` extracted — shared write/stats/audit/convert between single
  and batch paths; write stays sync (aiofiles adds nothing for 10ms writes)
- CLI `fetch` auto/quic modes route through the resumable path; audit rows
  carry the real on-disk byte count for resumed files
- tests: +4 resumable (hash mismatch drop / partial→Range resume assembly /
  hard failure surface / file_sha256) — 121 total; measured live: PDF
  2.4MB sha256 stable across channels (5a0bfc88), tar structure intact after
  multi-round resume (70 members, no splice corruption)

## [2026-09-03] feat | v0.16.11 — CN-aware acquisition transport (QUIC fallback)
> China-network reality (measured on a CN connection): arxiv.org TCP/443 is
> reset at the TLS-SNI layer (curl 5/5 RST) while UDP/443 QUIC is NOT —
> Chromium-based browsers reach arXiv directly. This release gives the
> download pipeline the same escape hatch as a browser.

- **new `hfpapers/arxiv_transport.py`** — layered acquisition chain
  `tcp (requests) → quic (aioquic, optional extra [quic]) → browser-hint echo`
  - `quic_fetch` / `async_quic_fetch`: HTTP/3 GET with CERT_REQUIRED chain
    verification + generous receive windows; refuses incomplete transfers
    (sha256 only recorded on stream-ended bodies — no silent truncation)
  - `quic_batch_fetch`: ONE connection, N concurrent streams — amortises the
    congestion-window ramp (measured: 3 PDFs / 11.5MB+1.4MB in one window
    where per-paper connections each took 30-90s)
  - source kind targets `/src/{id}` (tex tar.gz); `/e-print/` 301s; rejects
    the PDF arXiv serves when a submission has no tex bundle
  - `fetch_with_fallback` ends with a **browser-hint** echo telling an agent
    to use its Chromium/QUIC browser skill when every CLI transport fails
- **acquisition audit (MITM evidence)**: every attempt → append-only
  `data/download_audit.jsonl` (`event:"acquisition"`, transport/url/ok/ms/
  tls_verified/**sha256**/ts — failures recorded too); `scan_acquisitions()`
  flags **content-drift** (same paper+kind, different sha256 across channels
  = payload swap signature). aioquic exposes no peer-cert API client-side, so
  TLS integrity = CERT_REQUIRED chain check + cross-channel hash compare.
- **AsyncPdfDownloader**: TCP failure → automatic per-paper QUIC fallback
  (+ audit row); write path no longer hard-depends on optional aiofiles
- **new CLI `hfpclawer fetch <arxiv_id> [--kind pdf|source] [-t tcp|quic|auto]`**
  — single-paper channel test tool; saves to pdfs/ or sources/, logs audit
- tests: 18 new (URL mapping / payload magic incl. PDF-fallback rejection /
  tcp error mapping / fallback chain / aioquic-missing install hint /
  downloader QUIC fallback integration / audit drift alerts) — 117 total
- measured on CN network: PDF 2.4MB via QUIC 21s; tex bundles slower
  (single-stream UDP ~100 KB/s) — source fetches get a 180s budget

## [2026-09-03] fix | v0.16.10 — critical-audit round: four design defects fixed
> Independent self-audit (adversarial) of the v0.16 recommendation stack found 6 concrete
> failure scenarios; four were fixed in this round, two are recorded as known limitations.
- **scope discipline** (`profile.py`/`recommend.py`) — reject declarations now carry
  `scope: topic-exclusion | self-constraint`. Only topic-exclusion feeds the L0 gate;
  self-constraint ("WE don't use X") is documentation and MUST NOT filter papers ABOUT X
  (previous category error: "no telemetry here" hard-filtered telemetry research papers).
  `profile` CLI shows `[gate]` vs `[doc-only]`.
- **stale gate vs classics** (`recommend.py`) — the mechanical 180-day stale penalty now
  exempts `audit_level>=2` papers (content-verified): human-vetted foundational papers
  keep full weight instead of being buried by recency bias.
- **layer weights are real** (`rank.py`) — `build_dataset` returns `(X, y, w)` and
  training passes `sample_weight` to lightgbm. Pool layer confidence (manual 3.0 /
  verified 2.0 / favorited 1.5) previously existed only in documentation — the model
  treated all rows equally.
- **interest-signal revocation** (`sync_back.py`, `paper_store.clear_favorited`) —
  `zotero sync-back --revoke` reverts favorites whose Zotero Favor tag vanished
  (opt-in: the local API has no total-count, so revocation is never automatic —
  a truncated pull must not wipe live favorites).
- **A** `tests/` — 6 new tests (75 total): revoke×3, scope gate-vs-doc regression,
  stale-exemption, weight carrier.
- Known limitations (design-level, tracked): rank behavior-cloning loop (hub teaches
  itself; needs an independent golden set) · L0 substring recall has zero synonym
  handling (structural ceiling; L2a semantic layer is the roadmap fix).

## [2026-09-03] feat | v0.16.9 — REPO_USER.md v2: declarations as explicit feedback (SKILL.state)
- **A** `hfpapers/profile.py` — `ProfileVerdict`: one accept/reject declaration with explicit state machine (`active` consumed / `superseded` / `revoked` kept for audit — append-only decision history). Formatter: `type` (paper/method/domain/code) + `version` + `identifiers` {arxiv, doi} dual channel + `keywords` (L0 gate vocabulary) + `evidence` {file, lines} tex/markdown anchors + `reasons`.
- **M** `hfpapers/profile.py` — `RepoProfile.accepts/rejects` parsed in both AGENTS.md/REPO_USER.md and `~/.hfpclawer/profile.yaml` paths; `reject_keywords()` = active method-level vocabulary (placeholder-inert).
- **A** `hfpapers/recommend.py` — L0 reject gate: candidate whose title/abstract hits any active reject keyword is hard-filtered (repo + machine profile vocabularies; superseded/revoked inert) — declared rejections never surface.
- **M** `hfpapers/cli.py` — `init` REPO_USER.md template v2 (`schema: 2` + declarations skeleton); `profile` lists ✓/✗ declarations with state.
- **FIX** fence extraction rewritten as `_extract_yaml_fences()` (pure `str.find`, backslash-free): the editor/patch layer had escaped `\s` into `\\s` in the regex, silently breaking AGENTS.md parsing (masked by stale `__pycache__`; reproduced under `python -B`). Backslash-free patterns are immune to this class of tooling corruption.
- **A** `tests/test_verdicts.py` — 10 tests: v2 block parse, active-only consumption, vocabulary, placeholder inertness, identifiers, evidence anchors, reject-gate e2e.

## [2026-09-03] feat | v0.16.8 — open-source positive-example pool (roadmap §2e)
- **A** `hfpapers/pool.py` — append-only JSONL pool (`data/positive_pool.jsonl`, gitignored, zero telemetry). Layered weak labels decoupled from any user/repo: `verified` (audit_level≥1, w=2.0 — any clone user has these) / `manual` (w=3.0, explicit) / `favorited` (w=1.5, Zotero optional) / `adopted` (w=1.0, hub heuristic behavior cloning) / `truncated` (0, w=1.0 weak negatives). Suspect papers NEVER enter (abstain ≠ negative).
- **A** live gates — entry: store-suspect rejected at ingest/add; export: current-suspect papers filtered (pool kept append-only, verdicts reversible); adjudication: same arxiv_id conflicting layers → highest priority wins (verified > manual > favorited > adopted > truncated).
- **M** `hfpapers/paper_store.py` — `PaperRecord` gains `suspect`/`suspect_at` mirrors (v0.16.0 column existed; dataclass gap closed; get_status stays authoritative).
- **A** `hfpapers/cli.py` — `hfpclawer pool ingest|ingest-verified|sync-favorited|add|stats|export` (export output is rank-train compatible).
- **A** `tests/test_pool.py` — 11 tests: layered folding, idempotent re-ingest, append-only history, entry gate, live export filter + reversible, adjudication, corrupt-line skip.
- **Validation** — real store bootstrap: verified 14 + favorited 5 = 19 positives; negatives arrive via `pool ingest --audit` after hub expansions.

## [2026-09-03] feat | v0.16.7 — Zotero sync-back: Favor tag → favorited interest signal (Layer 2 adapter)
- **A** `hfpapers/paper_store.py` — Migration v4: `favorited` / `favorited_at` columns (idempotent — earliest sync timestamp kept). `PaperRecord` + `_row_to_record` carry the fields (guarded for pre-migration DBs).
- **A** `hfpapers/sync_back.py` — Favor-tag items → `ZoteroItem` contract → scholarly filter (DOI/arXiv only — web pages/programs/reports dropped BEFORE any lookup) → identifier match → `mark_favorited`. Zotero unreachable = empty stats, never raises (Layer 1 offline intact).
- **M** `hfpclawer/zotero/cli.py` — `cmd_sync_back` + `hfpclawer zotero sync-back [--tag Favor] [--dry-run]` (dry-run counts but writes nothing).
- **A** `tests/test_sync_back.py` — 6 tests: non-scholarly-only library, DOI match favorites, arXiv archiveID match, scholarly-not-in-store, dry-run, idempotent first-timestamp.
- **Validation** — LAN peer-side real run (portproxy): 300 Favor items → 236 non-scholarly filtered → 64 scholarly → 5 matched & favorited (MUSE stellarator ×2, optomechanical crystal, single-agent LLMs — all on-profile).

## [2026-09-03] feat | v0.16.6 — REPO_USER.md template (repo-scoped interest profile)
- **A** `hfpapers/cli.py` — `init` / `init --quick` generate `REPO_USER.md` template (never overwrites): neutral placeholder + built-in public-repo caution (real interests → `~/.hfpclawer/profile.yaml`, never committed).
- **M** `hfpapers/profile.py` — placeholder queries (`<...>`) excluded from `query_tuples` (unfilled template = empty profile, never pollutes recommendations); `REPO_USER.md` preferred over AGENTS.md.

## [2026-09-03] feat | v0.16.5 — Profile → recommendation pipeline (repo = virtual user)
- **A** `hfpapers/recommend.py` — fused query pool (config global + REPO_USER.md/AGENTS.md repo layer + `~/.hfpclawer/profile.yaml` machine user layer) → text-similarity recall → verification gate (suspect dropped, stale halved) → top-N with per-hit `why` provenance (layer + query).
- **A** `hfpapers/cli.py` — `hfpclawer recommend [--limit N] [--path repo_dir]`.
- **A** `tests/test_recommend.py` — 5 tests: pool fusion layering, gates (suspect drop/stale half-weight), why provenance, dry layers, docstring/signature smoke.

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