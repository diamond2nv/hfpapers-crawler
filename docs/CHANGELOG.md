# CHANGELOG

<!-- changelog-window rule="bytes<=24576" kept=8 of=9 bytes=22160 rotated=2026-09-22 -->




















> Newest first. Versions follow the **development line** (`main`, currently `0.18.x`).
> The **public line** is documented separately below: it has its own version sequence and a
> rewritten history, so the same work appears there under different commit ids.
>
> `scripts/changelog_guard.py` is the single implementation of "is this version documented?", and
> both `scripts/release.sh` and `tests/test_gates.py::TestChangelogGate` use it — a version cannot
> be tagged without an entry.
>
> The file is a **bounded rolling window**: when it grows past its byte budget, the oldest entries
> rotate into [`CHANGELOG-archive.md`](CHANGELOG-archive.md) (`scripts/changelog_rotate.py`; the
> window states its own rule in the comment above). Rotated entries stay findable — the guard
> searches both files.
>
> **Where releases live.** **GitHub releases** —
> <https://github.com/diamond2nv/hfpapers-crawler/releases> carries the public line, which has used
> the same version numbers as PyPI since 2026-09-17 (the retired `0.17.x` public sequence stays
> visible in history); **Release history** — <https://pypi.org/project/hfpclawer/#history> lists
> every published version with its upload date. PyPI can be **newer than the public repository's
> content**, because the `0.x.0` releases with odd `x` come from the development line — that is a
> property of the two lineages, not a missing release.
>
> **Provenance.** Entries down to **v0.16.14** were written at release time. Entries for
> **v0.17.0 – v0.18.14** were written **after the fact on 2026-09-17**, reconstructed from commit
> subjects, `git diff --stat <previous>..<tag>` and spot-checks against the code, because those
> releases captured no notes (17 of the 18 tags carried no message at all). Treat their wording as
> reconstructed narrative, and the code as the authority.

## Public line — sanitized recuts

The public repo (`github` / `mirror`) is not a push mirror of `main`: its history was rewritten for
release, and it is versioned on its own sequence (`0.17.x`) independently of the development line
(`0.18.x`). Tags `v0.17.0`, `v0.17.1` and `v0.17.2` point at **public-line** commits, which is why
the development line's own `v0.17.0` / `v0.17.1` release commits are untagged. Only the three
public cuts are listed here; their functional content is covered by the development-line entries.

### [2026-09-17] release | v0.19.0 — public snapshot, version-aligned with PyPI

- The public repository now carries the **same version numbers as PyPI** (policy change, rule 10 of
  `AGENTS.md`): PyPI accepts only `0.x.0` with an odd `x` for this project, so the public line uses
  those numbers too and the old `0.17.x` sequence is retired.
- Cut from the `v0.19.0` tag itself, so this commit's tree **is** the published 0.19.0 content
  (modulo sanitization), not a later development tip. Every version on PyPI — 0.5.0, 0.15.0, 0.17.0,
  0.19.0 — now has a same-named tag here.
- Tag SHAs differ per remote by construction: `v0.19.0` here is this sanitized snapshot, on the
  private mirror it is the development commit. The tag *name* is the shared identity; history is
  appended to, never force-pushed.
- Content carried: biomedical sources (Europe PMC / bioRxiv / medRxiv), the verification state
  machine, first-party recommendation signals, the `config.local.yaml` overlay, install-safe state
  paths (user directories instead of `site-packages`), the changelog coverage/window gates, the
  doc-surface audit, the deterministic-by-default test suite, and the dependency tiering
  (`nlp`/`zotero` extras + generated locks).

### [2026-09-21] maintenance | public line — drop the stale requirement lists (no version stamp)

- **M** public line `requirements/` — `requirements_all_0.1.3.txt`, `requirements_core.txt` and
  `requirements_dev.txt` deleted from the public tree. The sanitized recut copies the *content* of
  differing paths and never mirrors deletions, so the development line's 2026-09-17 removal never
  reached the public line: the 188-line **v0.1.3** freeze was the sole source of **all 55 open
  Dependabot advisories** (aiohttp / cryptography / mcp / scrapy / starlette / transformers / …).
  Open advisories: **55 → 0**. `env.template` (renamed to `.env.template` on the development line)
  went the same way. `recut-public.py` now **refuses a cut** when the public tree carries files the
  development line dropped (gate 3b + `tests/test_recut_public.py`).
- **A** Exo-suite cross-links — `README.md` / `docs/cn/README.zh-CN.md` (suite block, uv-first
  install, "light start, add heavy extras later", the `uvx`-reuses-an-old-tool-env trap) and the 10
  published ClawHub skills (entry skill `exo-suite-linkage`; `uvx` versions pinned for rug-pull
  hygiene; top-level `tags:` added where missing). No version stamp: a public cut carries the
  version of its own release.
- **note — a version stamp was retracted here (2026-09-21).** This entry was first written as a
  `v0.21.0` public cut. That cut was taken from the development *tip* (`0.19.7`) instead of from the
  development line's own `v0.21.0` tag, so it stamped unreleased 0.19-line content with a version the
  development line has not reached. The GitHub tag `v0.21.0` was deleted and the public tree was
  pinned back to `0.19.0`; the numbering stays with PyPI and with the development line's release
  tags (`0.x.0`, odd `x`). The rule is now enforced by the tool: `--version X` requires the
  development tag `vX`, and the cut defaults to that tag as its source ref.

### [2026-09-11] fix | v0.17.2 — remove real ORCIDs and third-party names from tracked files

- **M** `config.yaml`, `hfpapers/graph/**`, `hfpclawer/graph_cli.py` — de-identification recut of the
  public surface: real ORCIDs and researcher names replaced with the ORCID spec placeholder
  `0000-0002-1825-0097`. Equivalent to the development line's sanitization work.
- **note** — the public line's *history* still contains the earlier ORCIDs; the decision was not to
  rewrite it (force-push / filter-repo was explicitly declined), so the gate protects the future.

### [2026-09-11] fix | v0.17.1 — preserve the query string in the HTTP/3 `:path` pseudo-header

- **M** `hfpapers/arxiv_transport.py::_h3_path()` — same fix as the development line's `v0.17.1`;
  `urlsplit()` puts the query in `parts.query`, and building `:path` from `parts.path` alone dropped
  it, so parameterised endpoints failed at the server (`/oai?verb=` → `badVerb`, `/api/query?` → 400)
  instead of failing the transport. Payload endpoints carry no query, which hid the bug.
- **M** `docs/CHANGELOG.md`, `.env.template` — de-identification of the v0.16.14 entry and the env
  template (machine codenames → "LAN peer").

### [2026-09-05] feat | v0.17.0 — public release cut of the transport-layer work

- Public cut of the development line's `v0.17.0` (transport documentation for the QUIC fallback
  ladder, bounded-memory streaming, `.part` lifecycle, sha256 audit anchor, `fetch` CLI).

## [2026-09-17] fix | v0.18.23 — the test suite becomes a gate you can trust

> A suite that hangs, reddens for reasons unrelated to the code, or silently skips the
> plugin its own config declares cannot back any other claim in this repository. It was
> all three: it never finished (network tests without timeouts), it carried 12 failures
> nobody had triaged, and `asyncio_mode` plus a "deselected by default" marker were
> declared but never enforced.

### Two real bugs the "stale" tests were actually pointing at

- **M** `hfpapers/graph/citation_expander.py` — `HubGuidedExpander.run()` treated
  `stats["papers_found"]` as iterable whenever it was not a dict; on the count path (an
  `int`) that raised `TypeError: 'int' object is not iterable`, so the audit trail could
  never be written. The two failures in `tests/test_hub_guided_expansion.py` were a
  correct fake hitting a real defect — the code was fixed, the tests kept.
- **M** `hfpapers/cli.py` — `hfpclawer init --quick` crashed with `KeyError: 'file'`:
  the REPO_USER template contains literal YAML braces (`evidence: {file: ...}`) that
  `str.format()` consumed. Now `string.Template` with `${project}`; verified on a real
  run (`init` writes `config.yaml` *and* `REPO_USER.md`, braces intact).

### The suite is deterministic now

- **M** `pyproject.toml` — the default run is fixed by `addopts`:
  `-m 'not slow and not network and not integration'` (45 tests deselected). Passing `-m`
  on the command line overrides it. Markers re-documented: `slow` (builds a wheel/venv),
  `network` (live external service), `integration` (spawns real servers/CLIs).
- **M** `tests/test_integration.py` — module-level `pytestmark = integration`: the MCP
  stdio and HTTP dispatch tests spawn servers that never terminate in a bare environment
  (this is what hung the suite at 39%).
- **M** `tests/test_gates.py` / `tests/test_cli.py` — ambient-state leaks removed. The
  dedup gate depended on the developer's real database not containing the id it used
  (fixed with an isolated store + a dedicated id); the export tests read the real store
  and scraped an export path out of wrapped console output (now isolated and read from
  disk).
- **M** stale assertions retargeted to the current CLI: metadata download is
  `download-meta` (not `download`, which now downloads candidate PDFs), `monitor --help`
  documents `ACTION`/`--interval` rather than the action *values*, and the Zotero tests
  patch `_api_request` (renamed from `_api_get`). `init --quick` gained assertions for the
  crash above.
- **M** dev dependencies completed in both dev definitions (pip extras and PEP 735
  group): `pytest-asyncio`, `pytest-timeout`, `antlr4-python3-runtime==4.11.0` (sympy 1.14
  demands exactly 4.11; 4.13 fails with an ImportError that reads like a missing package).

### ⑤ dependency bookkeeping in the same pass

- **M** `pyproject.toml` — the duplicate `spacy` pin (core *and* `nlp`) collapsed to the
  core one, with the extra now adding only the model wheel; `pdf` marked as a
  compatibility alias (`pymupdf4llm` is core); `[dependency-groups].dev` aligned with
  `[project.optional-dependencies].dev` and commented on why both exist.

### Result

`pytest tests/` — **487 passed, 21 skipped, 45 deselected, 0 failed in ~64 s**; before:
never finished, 12+ failures. Suite runtime makes it usable as a release check.

## [2026-09-17] chore | v0.18.24 — the public-release tooling, and the doc-surface checks

> The v0.18.23 commit also carried the public-release tooling and the new doc-surface
> checks; recorded here so the changelog matches the commit (the entry above was written
> before those pieces were finished).

- **A** `scripts/recut-public.py` — the six-step public recut, mechanised: preflight
  (clean tree, `public` in sync with its remote, version above the latest public tag),
  scratch worktree, `git checkout main -- .`, **version re-set after the sync** (which
  silently reverts it), one commit signed with the public identity, then the three gates —
  changelog coverage, sanitization, and the snapshot's own test suite. `--dry-run` is the
  default and rolls the branch back; only `--push` publishes, through
  `scripts/publish-public.sh`, so there is a single push path.
- **M** `scripts/changelog_guard.py` — lineage-aware: a `###` entry inside the
  **public-line section** counts as documented, so a public release no longer has to be
  smuggled into the development list to pass. A `###` heading anywhere else is still a
  subsection, not a release — the previous protection is intact, just no longer applied
  to the one section that needs nesting.
- **M** `scripts/changelog_rotate.py` — rotation units are now top-level `##` blocks,
  sections included, so a section header travels with its nested entries into the archive
  instead of being glued to whatever entry preceded it.
- **M** `tests/test_gates.py` — three tests for the above: public-line entries count,
  stray subsections do not, and rotating the public-line section keeps its entries
  findable (the guard is asked again after rotation).
- **A** doc audit checks (C6/C7 in `scripts/doc_audit.py`): translation drift between
  `docs/*.md` and `docs/cn/*.zh-CN.md` beyond a tolerance, and tracked build/runtime
  artifacts. C6 immediately found `docs/ARCHITECTURE.md` 60 lines ahead of its mirror
  (the whole v0.16 state-semantics section had never been translated) — now translated,
  and `env.template` (an unreferenced duplicate of `.env.template`) is gone.

## [2026-09-21] fix | v0.19.7 — a low-confidence identifier can no longer land silently

> Three live occurrences in three days, all from Crossref auto-attach: a 2001 *Neuroreport* chapter
> DOI on an ICLR 2026 paper, a 2013 *Nature* news DOI on a long-context paper, and a 1990 psychology
> chapter DOI on a 2026 preprint — confidences 0.51–0.58. v0.19.6 *reported* that band; this release
> refuses it, at every call site.

- **M** `add_identifier(..., accept_unverified=False)` (`hfpapers/paper_store.py`) refuses any
  identifier below `invariants.LOW_CONFIDENCE_THRESHOLD` unless the caller passes
  `accept_unverified=True` or the record carries the `accepted-unverified` tag. Refusal is loud (a
  WARNING naming the escape hatch) plus an `identifier_rejected` event with the candidate, its
  confidence and the threshold; a deliberate acceptance is recorded too
  (`identifier_accepted_unverified`), so a wrong-but-intentional attach stays distinguishable from a
  wrong-and-unnoticed one. The return value now states what a caller must act on: `False` = nothing
  written (refused or error), `True` = the row is present afterwards.
- **A** `PaperStore.crossref_attach()` — the single place the store decides a Crossref candidate,
  returning `"attached"` / `"refused"` / `"none"`. `"refused"` writes nothing **and rewrites
  nothing**: the sub-threshold hit also used to stamp its own `venue`/`year` — the half of the live bug
  that made a 2026 preprint look like a 1990 psychology chapter. `ensure_paper`, `store ensure` and
  batch verification all route through it, so a new call site cannot side-step the gate.
- **M** `hfpclawer/audit/cron_verify.py` + `scripts/hfpclawer-audit-verify.py` both ignored the
  verdict, still counting a refused candidate as found and still stamping `venue`/`year`. They now
  report it as `doi_rejected` and leave the record alone — the scheduled path was the one most likely
  to run unattended.
- **F** `store ensure --accept-unverified` — the route as first written did nothing: it tagged the
  record and re-ran, but `ensure_paper` returns early for an existing record, so no candidate was ever
  attempted. It now tags the record and runs the attach explicitly, printing the verdict.
- **A** `tests/test_confidence_gate.py` (13 cases) — refusal, boundary, both acceptance routes (via
  `add_identifier` and via `crossref_attach`), the three verdicts, and the batch-verify path.
  `tests/test_invariants.py` seeds its risky DOI with SQL now: the invariant's job is the rows the
  write path never saw (a restore, a snapshot import, an older writer) — what the gate cannot police.
- **Scope** — development line only: PyPI takes `0.x.0` with an odd `x`, so this reaches PyPI with
  the next `0.21.0`.

## [2026-09-19] feat | v0.19.6 — review-driven: invariants as a gate, events for every row change

> `docs/AUDIT_CRITIQUE.md` measured the store rather than reading it and found 25 DOIs belonging to
> other papers, 14 impossible years, 18 duplicate records and 21 identifier-less records — while every
> existing gate was green. This release turns the critique into machinery: a deterministic gate over
> the artifact, a row-level event log, and one command for the merge that had been done by hand.

- **A** `hfpapers/invariants.py` — offline checks (year domain, missing identifiers, title hygiene,
  identifier vocabulary, low-confidence DOIs, non-paper DOI shapes, duplicate identity) with a
  coverage report; **A** `hfpapers/invariants_network.py` — the opt-in sampled DOI ↔ Crossref title
  check, so the core stays instant and offline.
- **A** `hfpclawer store invariants [--strict|--json|--network|--update-baseline]` — per-check counts
  plus a **ratchet baseline** (kept beside the store): a check that grew fails the gate, a check that
  shrank is reported. A gate that is red on day one gets ignored; a gate that can hide findings is
  worse.
- **A** row-level event log (`store_events`, migration v6) with `store events`: identifier
  add/remove/**transfer**, record removal (full row snapshot inside the event), `item_type` decisions
  and pre-destructive snapshots. `store snapshot` writes the full store on demand.
- **A** `store dedup [--apply]` — groups by `identity_key`, keeps the identifier-richest record,
  refuses mismatched titles and same-work/different-artefact pairs (a journal paper and its OSTI
  report are two records, not a duplicate), snapshots first, **verifies every identifier moved before
  deleting anything**.
- **M** one canonical `paths.pdf_dir()`: two directories held 62 PDFs between them and `fetch` wrote
  to the one the audit never reads; the stray files are moved and the divergent defaults collapse.
- **M** `derive_item_type` inputs unchanged, but the two defects the invariant found in practice —
  a classifier fed by a venue inherited from a wrong DOI, and a `--limit` that silently capped a
  backfill at 20 of 1182 — are now recorded rather than silent.
- **Tests** `tests/test_invariants.py` (29 cases) — every check has a failing example from the live
  store, a clean store stays quiet, the ratchet detects regressions, and `dedup` proves the
  identifier-move verification that the manual merge lacked.
- **Scope** — development line only: PyPI takes `0.x.0` with an odd `x`, so this reaches PyPI with
  the next `0.21.0`.

## [2026-09-19] feat | v0.19.5 — what a record *is*: `item_type`, learned from Zotero

> `venue` was doing three jobs at once (container title, repository name, arXiv category) and 48%
> of rows had none; material class lived in hand-applied free-text tags. A store that cannot
> answer "is this peer reviewed?" cannot back a citation claim, so every record now carries a
> **carrier form** from a closed vocabulary borrowed from Zotero's `itemType` names.

- **A** `hfpapers/item_types.py` — the vocabulary (`journalArticle`, `conferencePaper`,
  `preprint`, `report`, `thesis`, `book`, `bookSection`, `dataset`, `software`, `webpage`, plus
  our `unknown`), peer-review status *derived* from the type rather than stored beside it, and a
  pure `derive_item_type(...) -> (item_type, reason)` that needs no network. Three ordered rules
  exist because the store was wrong without them: explicit markers beat naming heuristics;
  "under review" beats a conference acronym (`arXiv:2508.04349 (ICLR 2026 under review)` is a
  preprint, not an ICLR paper); and marker matching is **word-bounded**, so `synthesis` no
  longer fires the `thesis` marker and `Oracle` does not fire `acl`.
- **M** `hfpapers/paper_store.py` — migration v5 adds `item_type`, `item_type_src`
  (`derived` / `manual`) and `item_type_at`, plus `set_item_type`, `get_item_type`,
  `item_type_stats`, `item_type_coverage` and `iter_item_type_inputs` (one query per pass, tags
  read through the identifier table).
- **A** `hfpclawer store types | classify | set-type` — inventory, a dry-run-first backfill
  (`--apply`, `--all`, `--max`) and single-record correction. `--limit` prints rows while
  `--max` bounds the work: they were one option once, and a backfill silently wrote 20 of 1182.
- **A** `docs/ITEM_TYPE.md` — what was copied from Zotero and what was deliberately left out
  (per-type field tables, typed creators, child items), the three-axis model
  (item_type × venue × source), how to extend the rules, and the known limits.
- **Backfill** — 1182 records classified: preprint 821, journalArticle 260, conferencePaper 89,
  report 7, webpage 1, unknown 4. `unknown` is a first-class answer, reported separately from
  "never classified", and a manual decision is never overwritten by a rule.
- **Scope** — development line only: PyPI takes `0.x.0` with an odd `x`, so this reaches PyPI
  with the next `0.21.0`.

## [2026-09-19] fix | v0.19.4 — the importer stops writing placeholder metadata when arXiv is unreachable

> A 245-reference batch ingest left records titled with their own arXiv ids (`title = "2604.10098"`,
> `year = 0`) while the CLI printed a success line for each of them. Three causes, one symptom: the
> metadata call used `http://`, had no retry, and had no fallback source — and the failure was
> swallowed inside the importer, so nothing upstream could notice.

- **M** `hfpclawer/import_paper/importer.py` — `_fetch_arxiv_meta` split into `_parse_arxiv_atom`
  (pure parsing, testable without a network) plus a fetch path that uses **https**, retries with
  backoff, and falls back to **DataCite**; `ImportResult` gains `metadata_source`, so an unresolved
  record is now an explicit `""` instead of an empty title.
- **A** placeholder guard — when no source resolves, the importer warns rather than writing the raw
  identifier as a title; batch runners key their backfill on `metadata_source == ""`.
- **Evidence** — reproduced on a real batch (245 references, Attention-Sink survey): 102 records
  carried unusable metadata until a DataCite/Crossref backfill repaired them. The import path is now
  covered by `tests/test_import.py`.
- **Scope** — development line only: PyPI takes `0.x.0` with an odd `x` for this project, so 0.19.4
  stays on the private line and reaches PyPI with the next `0.21.0`.

## [2026-09-17] docs | v0.19.3 — one release-surface pair, stated the same way everywhere

> The two release links were described four different ways (README, this header, `pyproject.toml`,
> the GitHub release notes), and this header still claimed the public line runs on its own `0.17.x`
> sequence — retired by the version-alignment policy of 2026-09-17. Same URLs, one phrasing.

- **M** `docs/CHANGELOG.md` (header) — **GitHub releases** keeps its URL and is now described as the
  public line *on the same version numbers as PyPI* (the retired `0.17.x` sequence stays visible in
  history); the second link is labelled **Release history**, matching `README.md` and
  `[project.urls]` in `pyproject.toml`.
- **M** GitHub release `v0.19.0` (published surface, edited in place) — carries the same pair, so a
  visitor arriving from PyPI finds where releases live without leaving the page.
