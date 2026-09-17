# CHANGELOG — archive

> Entries rotated out of `docs/CHANGELOG.md` (newest first). The live file keeps a bounded window
> because a changelog is read, not diffed: the rule and the tool that implements it are
> `scripts/changelog_rotate.py`, and the window state is recorded in an HTML comment at the top of
> the live file.
>
> Nothing is lost by rotation — every past state of `docs/CHANGELOG.md` is also preserved in git
> (`git log -- docs/CHANGELOG.md`).

## [2026-09-17] docs | v0.18.17 — stop the doc surface from lying about v0.17/v0.18

> A mechanical audit of `docs/`, `skills/` and `AGENTS.md` (referenced paths, documented CLI
> commands, version claims, coverage drift) found ten defects; all of them are documentation
> drift introduced or exposed by the v0.17/v0.18 work.

- **M** `AGENTS.md` — the canonical agent guide claimed **"Current version: 0.3.0"** (15 minors
  stale) and "Version defined in `hfpapers/__init__.py`", contradicting the PEP 621 single-source
  rule the code implements; also a tag example outside this repo's scheme (`v3.1.0`), a release
  example from 0.9.x, a stale `.gitignore` inventory, and the assertion that the pre-push hook
  "已移除" — it is installed again with different duties (version on `main` only + sanitization).
- **M** `docs/ROADMAP.md` — read as if v0.16 were the tip, with planned items indistinguishable
  from shipped ones. Added a shipped-vs-planned table: `ledger` / `check-new` / `pool` / `rank` /
  `recommend` shipped; **`hfpclawer run`, `data/golden_positive.jsonl`, `scripts/migrate_status.py`
  never existed** (migration became idempotent ALTERs in `_init_db`).
- **M** `README.md` — the feature list stopped at v0.16.9, so a reader could not learn that the
  biomedical sources, the private-config overlay or the gate stack exist.
- **M** `docs/USAGE.md` + zh / `docs/ARCHITECTURE.md` + zh / `skills/hfpclawer-paper-search/SKILL.md`
  — the multi-source registry (`SOURCE_CLASSES`, `search.enabled` vs `sources.<name>`, the shared
  retry policy, dedup keys, the `config.local.yaml` overlay) was documented nowhere; added,
  mirrored (line-aligned) in both languages.
- **M** `docs/USAGE.md`, `docs/DISTRIBUTED.md` + zh — both documented **`hfpclawer crawl`, which is
  not a command**; replaced with the real entry points (`search`, `source-list`,
  `source-search <source> <query>`) and marked the legacy Scrapy-queue path as never implemented.
- **M** `docs/use/verify-guide.md` + zh — pointed at `docs/formula-cross-validation-architecture.md`,
  which does not exist; now marked as planned (mirror kept line-aligned).
- **M** `docs/ARCHITECTURE_REVIEW.md` — the same "never built" script annotated where it appears.
- **M** `docs/CHANGELOG.md` — the v0.18.6 entry named `tests/test_sources_retry.py`; the file is
  `tests/test_source_retry.py`. Found by the audit, not by hand.
- **A** `scripts/doc_audit.py` — the audit itself, kept as an **advisory** tool (coverage is a
  judgement call; the enforceable invariants stay in `tests/test_gates.py` and `scripts/pre-push`),
  with deliberately-absent references whitelisted so the output stays scannable.
- **M** `.gitignore` — `sources/` (arXiv source bundles) was untracked but unignored, leaving
  `git status` permanently dirty.

## [2026-09-17] chore | v0.18.16 — bound the changelog: rolling window + archive

> A changelog is read, not diffed. v0.18.15 left it at 44 KB and growing ~2 KB per release, with no
> ceiling and no rule — the same failure mode as the missing entries, one step later.

- **A** `scripts/changelog_rotate.py` — the single implementation of the window rule, modelled on the
  wiki's `rotate_log.py`: **one criterion = bytes** (default 24576 B), keep the newest contiguous
  entries, floor of 8 / ceiling of 40 kept, refuse to rotate below the floor rather than lose
  history, idempotent when already inside budget, and a self-describing
  `<!-- changelog-window rule="bytes<=24576" kept=… of=… bytes=… rotated=… -->` comment.
- **A** `docs/CHANGELOG-archive.md` — append-only destination for rotated entries (newest first),
  created by the first rotation: 21 entries (`v0.16.10` … `v0.9.13`) moved out, window now holds 23
  entries (`v0.18.15` … `v0.16.11`). Conservation is asserted, not hoped for: entry accounting must
  balance and no heading may exist in both files.
- **M** `scripts/changelog_guard.py` — searches the archive as well as the live file. Without this,
  rotation would make an old release read as undocumented; the gate caught exactly that during
  development (`v0.16.0` moved out and the check went red).
- **M** `scripts/release.sh` — a second pre-tag gate: refuses to release while the window is over
  budget (`--check`), with the fix command in the message.
- **M** `scripts/changelog_rotate.py --verify-history` — the rotation-aware version of "no heading may
  vanish": entries may *move* between the live file and the archive, but the union of both is
  compared against the union at `HEAD`. Without it, every rotation looks like a deleted heading to a
  single-file check (`md-heading-guard` reports exactly that, by design — for `CHANGELOG.md` this
  mode is the right gate; keep `md-heading-guard` for hand-edited docs).
- **M** `scripts/release.sh` — third pre-tag gate: refuses if an entry disappeared from live+archive.
- **M** `tests/test_gates.py` — `TestChangelogWindowGate` (F04): window within budget, window
  self-describing, no entry in both files, idempotency, conservation across rotation, refusal below
  the floor, and no entry lost vs `HEAD`. Also fixes a pre-existing ruff `F541`.
- **M** `docs/DEVELOPMENT.md` + `docs/cn/DEVELOPMENT.zh-CN.md` — release-gate section (kept
  line-aligned, 182/182). `AGENTS.md` docs table gains the archive row.
- **note** — git remains the full record (`git log -- docs/CHANGELOG.md`); the archive exists so a
  reader does not need git to see the older history.

## [2026-09-17] chore | v0.18.15 — backfill the changelog for v0.17.0–v0.18.14, and gate it

> Documentation debt closed. 18 tagged releases had no entries, and nothing in the repository could
> have noticed: the changelog was named in a docs table and enforced nowhere.

- **A** `scripts/changelog_guard.py` — the single implementation of "is this version documented?",
  with a boundary-anchored version match (`v0.18.10` must not satisfy a lookup for `v0.18.1`).
- **M** `scripts/release.sh` — refuses to tag an undocumented version, and the check runs **before**
  the dry-run branch so the gap surfaces on `--dry-run` too.
- **M** `tests/test_gates.py` — `TestChangelogGate` (F03) drives that same script through its CLI
  (one rule, two callers, no second copy), including the prefix trap, the "public-line `###`
  subsections are not release entries" case, and the non-semver / missing-file exit codes.
- **M** `docs/CHANGELOG.md` — 18 reconstructed entries, the three public-line recuts moved to their
  own section with the two-lineage explanation, and the file re-ordered: the `# CHANGELOG` title had
  been sitting *inside* the v0.10.0 entry with v0.10.x entries above it, and the tail was not
  date-monotonic. Rewritten programmatically with heading-preservation and byte-identity assertions,
  not by hand.
- **note** — the 18 entries are reconstructed, not contemporaneous (see the provenance note at the
  top of this file); their claims were spot-checked against the code: `deduplicate()` key priority,
  `search.enabled`, `journalInfo.journal.title`, `_get()` retry config, `SourcePaper.year`, the
  `__init__` version reader, `_h3_path()`.

## [2026-09-15] docs — public-surface correction: the Aliyun mirror is semi-public
> No version tag: this fix landed on `main` after `v0.18.14` and ships with `v0.18.15`.

- **M** `AGENTS.md` — the Aliyun Codeup remote is described as **semi-public** (a private-repo cloud
  backup, not a public host), instead of being grouped with the public remotes.

## [2026-09-12] docs | v0.18.14 — correct stale remote guidance and record the branch/release structure

- **M** `AGENTS.md` — remotes documented as they actually are (`forgejo` = NAS, `github` = public,
  `mirror` = Aliyun semi-public, `origin` = internal GitLab), plus the branch convention
  (`main` = development line, `public` = public line) and the two-lineage tag caveat.

## [2026-09-11] docs | v0.18.13 — record who is allowed to publish

- **M** `scripts/publish-public.sh` — header states the authorization scope: of the LAN machines only
  the primary machine holds public-release credentials, so the others push to NAS and stop. A remote
  machine failing at the push step is therefore expected behaviour, not a broken setup.

## [2026-09-11] feat | v0.18.12 — push gate covers sanitization; public release scripted

- **M** `scripts/pre-push` — now two gates: **version consistency**, scoped to `refs/heads/main`
  only (the public line has its own version sequence, which the old unconditional check flagged as a
  false mismatch), and **sanitization**, applied to every push: it scans the pushed commits' tracked
  files for real ORCIDs, private IPs, machine codenames, emails and tokens.
- **A** `scripts/publish-public.sh` — the public-release entry point (`--status`, `--check`,
  `<version> --push`): refuses to move an existing tag, pushes with an explicit `public:master`
  refspec, and reads back what it pushed.
- **note** — the gate scripts are on the allow-list of their own scan (a file that defines the
  patterns necessarily contains them); self-reference is expected and deliberately not obfuscated.

## [2026-09-11] fix | v0.18.11 — version-number guard for the sanitization gate

- **M** `AGENTS.md` — the private-range pattern for `10.x` gained a lookbehind that keeps URLs and
  hosts while dropping dependency pins such as `nvidia-curand==10.4.0.35`, which otherwise buried
  real findings in noise.

## [2026-09-11] fix | v0.18.10 — the sanitization gate could not see what it was meant to protect

- **root cause** — the documented gate scanned private IPs and machine codenames only. Real ORCIDs,
  personal names and emails walked straight through it, so the check reported "clean" while the very
  category it existed for sat in tracked files. A check that cannot see its target category is worse
  than no check: it grants false confidence.
- **M** `AGENTS.md` — gate command extended to ORCIDs, personal emails, tokens and `10.x`.
- **M** `config.yaml`, `hfpapers/graph/orcid_fetcher.py`, `hfpapers/graph/sources/orcid_enrich.py`,
  `hfpapers/graph/sources/wiki.py`, `hfpclawer/graph_cli.py`, `hfpapers/graph/viz/geo_map.py` — what
  the widened gate exposed: 11 real ORCIDs and third-party names de-identified to the ORCID spec
  placeholder `0000-0002-1825-0097`.
- **note** — an ORCID is public by design (its registry needs no auth); what is sensitive is the
  aggregate "who + which institution" list, which maps a research network.

## [2026-09-11] docs | v0.18.9 — biomedical method-transfer mapping table

- **A** `docs/spec/biomed-method-transfer-2026-09-11.md` — 36 mappings from biomedical-paper methods
  onto this repo's modules, each traceable to a DOI. Verified independently of the author of the
  table by querying the repo's own Europe PMC source (37/37 DOIs resolved), and it lists what could
  not be evidenced rather than padding the table.

## [2026-09-11] fix | v0.18.8 — Europe PMC venue was read from a key that does not exist

- **root cause** — `_parse` read a flat `journalTitle`; the `core` response has no such field (the
  journal sits at `journalInfo.journal.title`), so `venue` was silently empty. What kept it alive
  was the test fixture: it had invented the same flat key instead of copying a real response, so
  fixture and implementation shared one wrong assumption and the test stayed green forever.
- **M** `hfpapers/sources.py` — read the nested path.
- **M** `tests/test_sources_biomed.py` — fixture rewritten to the real shape plus an assertion on
  `venue`; measured on a 25-item batch: non-empty `venue` 0/25 → 23/25.

## [2026-09-11] feat | v0.18.7 — declare the biomedical query slot in the public config

- **M** `config.yaml` — `search.biomed_queries: []` plus a comment; the real queries belong in the
  gitignored `config.local.yaml` overlay, keeping third-party research interests out of the public
  file.

## [2026-09-11] fix | v0.18.6 — the retry policy existed in config and nobody consumed it

- **root cause** — all six sources did `if resp.status_code != 200: return []`, while `config.yaml`
  had advertised `anti_crawl.max_retries` / `retry_http_codes` / `retry_delay_base` the whole time.
  A single transient 503 therefore dropped a whole batch silently — observed as "the source returned
  nothing", with no error and no warning. Config that nobody reads is a promise, not a feature.
- **M** `hfpapers/sources.py` — `PaperSource._get()` reads that config (attempts, retryable codes,
  linear backoff), retries connection errors too, returns immediately on a non-retryable code (404),
  and all six sources now route through it.
- **A** `tests/test_source_retry.py` — retry count and backoff asserted, with `time.sleep` patched
  out (otherwise the test would really wait 30s per attempt).

## [2026-09-11] feat | v0.18.5 — sensitive config moves to a gitignored overlay; version reader fixed

- **A** `config.local.yaml` (gitignored) + `hfpapers/config.py` `_deep_merge` / `_load_local_overlay`
  — `config.yaml` is tracked **and public**, yet carried 11 real ORCIDs and 12 real researcher names
  under `stepping.layers`. That block moved to the local overlay; the public file keeps `layers: []`.
  Verified by merge: 5 layers / 12 names / 11 ORCIDs still resolve locally, and none of it is in the
  public file.
- **M** `hfpapers/__init__.py` — read the local `pyproject.toml` first, with `importlib.metadata` only
  as the installed-wheel fallback. The old order kept reporting the previously installed version in a
  checkout, so the version gate failed on every bump until the editable install was refreshed.
- **note** — the overlay replaces lists wholesale, so only whole lists can be overridden. A test can
  inject the overlay through `_TEST_HFPAPERS_LOCAL_CONFIG`.

## [2026-09-11] fix | v0.18.4 — the enabled-source list was read from a key that does not exist

- **root cause** — `get_enabled_sources()` read `sources.enabled`; the real key is `search.enabled`.
  The lookup could never match, the default always won, and four configured sources ran as one —
  silently, because a default that happens to work looks like normal behaviour.
- **M** `hfpapers/sources.py` — read `search.enabled`; the regression test records every config key
  the function asks for and asserts the correct one is among them, rather than only checking output.

## [2026-09-11] feat | v0.18.3 — one registry table for sources

- **M** `hfpapers/sources.py` — `SOURCE_CLASSES: dict[str, Callable[[], PaperSource]]` plus
  `get_enabled_sources()`. Registration is not enablement: a new source does not enter
  `search.enabled` by itself, so adding one cannot change existing behaviour.

## [2026-09-11] fix | v0.18.2 — dedup silently dropped every record without an arXiv id

- **root cause** — `deduplicate()` keyed on `arxiv_id` alone, written as
  `if p.arxiv_id and p.arxiv_id not in seen`. Records without one were therefore not *merged* but
  *dropped*, and biomedical sources are DOI/PMID-only — the entire new output would have been eaten.
  Measured: two DOI-only records in, `len(result) == 0` out.
- **M** `hfpapers/sources.py` — key priority `arxiv_id` → `doi` (case-insensitive) → normalised
  title, and records with no usable key are kept. First-occurrence-wins behaviour is unchanged.
  General pattern: a function that mixes filtering with deduplication will silently empty the data
  the day it meets a new input type.

## [2026-09-11] feat | v0.18.1 — bioRxiv/medRxiv preprint source

- **M** `hfpapers/sources.py` — `BiorxivSource(server=...)`. The endpoint offers no keyword search,
  only date ranges (`api.biorxiv.org/details/<server>/<start>/<end>/<cursor>`), so keyword filtering
  belongs at the ingest side rather than inside `search(query)`; abstracts are available.

## [2026-09-11] feat | v0.18.0 — Europe PMC biomedical source

- **M** `hfpapers/sources.py` — `EuropePmcSource`. Two field-shape traps were caught by read-only
  probing *before* implementation: the default response carries 27 fields and **no abstract**
  (`resultType=core` is required for 41 fields plus `abstractText`), and `pubYear` is a string.
  Without the probe, the source would have ingested hundreds of empty abstracts without erroring.
- **M** `hfpapers/sources.py` — `SourcePaper.year: int = 0` added; the field was absent, so passing
  `year=` raised `TypeError`. Defaults keep the four existing sources unaffected.
- **A** `tests/test_sources_biomed.py` — samples keep the real field shapes (including the
  string-typed year) but every identifier value is a placeholder, so no real author name, DOI or
  PMID is tracked in a public repo.

## [2026-09-11] fix | v0.17.1 — HTTP/3 request path dropped the query string

- **root cause** — `urlsplit()` puts the query into `parts.query`, but the HTTP/3 `:path`
  pseudo-header was built from `parts.path` alone. Every parameterised endpoint then failed *at the
  server* with a generic error rather than failing the transport: `/oai?verb=...` → `<error
  code='badVerb'>`, `/api/query?...` → HTTP 400. Payload endpoints (`/pdf`, `/src`) carry no query,
  which is why it stayed hidden while QUIC was only wired to pdf/source.
- **M** `hfpapers/arxiv_transport.py` — `_h3_path()` builds `path` + `?query`; for query-less URLs it
  returns `parts.path` byte-identically, so pdf/src behaviour is unchanged.
- **A** `tests/test_arxiv_transport.py` — 7 new cases (`TestH3Path`, including a call-site guard);
  5 of them go red on the pre-fix module. Effect of the fix: QUIC now also serves arXiv metadata
  hosts under a full TCP reset (oaipmh ListRecords 4,061,181 B / 1,300 records / 963 ms;
  `export.arxiv.org/api/query` 6,911 B; `/abs/<id>` 44,357 B; `/list/cs.AI/recent` 91,521 B).

## [2026-09-05] feat | v0.17.0 — transport-layer documentation lands (covers v0.16.11–v0.16.14)

- **M** `docs/ARCHITECTURE.md`, `docs/USAGE.md` and their `docs/cn/` counterparts — the QUIC
  fallback ladder, bounded-memory streaming, `.part` lifecycle, the sha256 audit anchor, the
  payload-validation fix and the `fetch` CLI.
- **M** `skills/hfpclawer-paper-search/SKILL.md` — the `fetch` section.
- **note** — a cross-channel check was recorded at the time: a direct QUIC fetch and an AlphaXiv
  mirror copy of the same paper hashed byte-identical, which is the reliability evidence for the
  transport (per-fetch hashes land in `data/download_audit.jsonl`).

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
  size, never renamed** (2026-09-05 LAN-side measured: 3,947,319-byte tar.gz arrived
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
- **Validation** — LAN-side real run (via a private host portproxy): 300 Favor items → 236 non-scholarly filtered → 64 scholarly → 5 matched & favorited (all on-profile).

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

## [2026-07-12] feat | spaCy NLP subpackage (v0.9.13)
- **A** `hfpapers/nlp/` — 6-module NLP subpackage: keywords (lemmatization), search (vector reranking), innovation (5-7 point extraction), tags (auto-tag generation), tag_analysis (TF-IDF library scan)
- **M** `hfpclawer/zotero/__init__.py` — Wire spaCy into `_title_keywords`; L1b semantic rerank; `update_item_extra()`
- **M** `hfpclawer/zotero/cli.py` — `cmd_innovate`, `cmd_tag_report`
- **M** `hfpapers/cli.py` — Wire `innovate` and `tag-report` actions
- **M** `pyproject.toml` — `[nlp]` and `[nlp-full]` optional deps

## [2026-07-12] feat | cron CLI + cron-verify audit + no_agent script
- **A** `hfpclawer/audit/cron_verify.py` — Batch Crossref verify + retraction check module for cron-imported papers (VerifyStats dataclass, batch_verify(), format_report(), format_report_json())
- **A** `hfpclawer/cli_cron.py` — `hfpclawer cron {init,check,run,import}` CLI subcommands (3-tier DB path resolution, arXiv API search, paper_store import with skip_crossref=True, config.yaml generation)
- **A** `scripts/hfpclawer-cron-fetch.sh` — no_agent mode shell script (0 LLM token, --json/--help modes, auto venv detection)
- **A** `docs/cron-guide.md` + `docs/cn/cron-guide.zh-CN.md` — Bilingual user guide (quickstart, commands, DB path, verification pipeline)
- **M** `hfpapers/cli.py` — Register `cron` command + `audit cron-verify` action in ACTION_DESCRIPTIONS

## [2026-07-12] docs | Knowledge Graph v0.10.x roadmap + plan
- **A** `docs/ROADMAP.md` — v0.10.x knowledge graph roadmap
- **A** `docs/plans/knowledge-graph-v0.10.md` — Detailed implementation plan (~1600 lines, 7 node types, 7 edge types)
- **M** `AGENTS.md` — Add Environment and Connectivity section

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
