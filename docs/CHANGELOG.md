# CHANGELOG

<!-- changelog-window rule="bytes<=24576" kept=7 of=7 bytes=23155 rotated=2026-10-26 -->

## [2026-10-26] feat | v0.20.2 — `scripts/` gets a registry, and the registry is a gate

`scripts/` held 30 tracked files and only six carry a criterion. The map from file to
responsibility lived in untestable prose, so adding a script was silent, retiring one invisible,
and a `gate` with no consumer looked exactly like a working gate.

* `scripts/AGENTS.md` — the nested guide, built for progressive disclosure: root `AGENTS.md` hands
  off to it, it hands off to each script's docstring, and §0 says which section answers which job.
  §1 注册表 (类型/入口/调用者/判据/状态), §2 判据 (command + exit codes + who consumes + the publish
  chain's gate order), §3 依赖 (tools, script→script graph, single-source patterns, external state),
  §4 生命周期 (add/modify/retire + the `SUPERSEDED by <file>` header convention).
* `tests/test_scripts_registry.py` — five gates parse the document: coverage (no unregistered file,
  no phantom row), vocabulary, every `gate` needs a §2 exit-code contract, every `superseded` row
  must say `SUPERSEDED` in its own header, every `gate` needs a consumer outside itself. Proven by
  mutation: dropping an unregistered `scripts/zz_unregistered_probe.sh` turns it red naming the
  file; removing it goes green. It also joins `SNAPSHOT_TESTS`.

Two real defects fell out, fixed not documented: `version-check.sh` was a gate with
**no consumer** (nothing ran it; the Forgejo runner is not always on) — `release.sh` now calls it
*before* the bump, so drift cannot be promoted into "the new version"; and the entry-column rule
caught three template rows that described a copy operation instead of an entry point.

Also fixed on the way: `changelog_rotate.py --refresh` corrects a stale `bytes=` without moving an
entry, and `MIN_KEEP` 8 → 6 — with ~3 KB entries, eight of them sit exactly at the budget, so the
floor and the budget deadlocked and the next release could not write its entry at all.

Verified: the five gate suites rc 0, ruff clean, `sh -n scripts/release.sh` ok, `doc_audit.py` 0
findings.

## [2026-10-26] fix | v0.20.1 — the scratch worktree was deleted but never unregistered

The publish path runs in a temporary worktree. When it finished it removed the *directory*
(`shutil.rmtree`) and nothing else, so the registration under `.git/worktrees/recut-public-…`
stayed behind — still holding the branch. Measured minutes after v0.20.0 went out:
`git worktree list` showed the deleted tree as `prunable`, and the next
`git worktree add <path> public` refused with *"'public' is already checked out at
/tmp/recut-public-6bboakpv"*. One ghost per publish, and a branch that looks busy to every
later cut.

* `dispose_worktree()` removes through git first (`worktree remove --force`), deletes the
  directory, then prunes. Both the dry-run rollback and the publish path call it, so the two
  cannot drift apart again; an unexpected exception still keeps the tree for inspection and
  `--keep-worktree` keeps it deliberately.
* `scripts/release.sh` no longer carries a `--push` path. It pushed to `origin` (the lab's
  internal GitLab) **with `--tags`** — the wrong remote per AGENTS.md (`forgejo`), and a
  tag-leak path now that the public line refuses non-release tags. The flag is refused and the
  two documented commands are printed instead.

Verified: `tests/test_recut_public.py` gains
`test_dispose_worktree_removes_the_registration` — build a worktree, dispose it, assert the
registration is gone **and** the branch can be checked out again (the exact failure the ghost
caused); suite rc 0, ruff clean, pyright 0 errors, `sh -n scripts/release.sh` ok, and the
v0.20.1 sync left `git worktree list` with no ghost entry.

## [2026-10-26] feat | v0.20.0 — the public line learns to follow the development line (release | sync)

The public line had one rule for two different questions — *may this version be published?* and
*may this tree go out at all?* — and gave the same answer to both, so nothing in between could go
out. Measured before this release: the development line was **53 commits ahead** of the public
line, and the public tree carried development content (0.19.7-era) under the `0.19.0` stamp it had
been published with. Two trees, one number.

* `scripts/recut-public.py` gains `--mode {release,sync}`. A **release** is unchanged (odd `0.x.0`;
  tag + GitHub Release + PyPI upload). A **sync** snapshots any development release tag and
  publishes **no** tag, **no** Release and **no** upload: one commit on the default branch whose
  message (`sync(public): vX.Y.Z — not a release`) and `Public-Sync:` / `Dev-Tag:` trailers make
  the advance machine-readable.
* the accept/refuse matrix is now one pure function, `judge_request()`, tested directly —
  release-version rule (release only) · development tag required by **both** modes · version must
  beat the **high-water mark** (both) · a sync may not publish an *older* development release than
  the newest one (`--allow-stale-source` overrides; older content behind a higher number is the
  same trap mirrored). `public_high_water()` reads the mark from release tags **and** `Public-Sync`
  trailers, because tags stop telling you where the line is once syncs exist.
* `scripts/pre-push` gate 4 covers the risk the split creates: against the public remotes it
  refuses any tag that is not `v0.<odd>.0` (a stray `git push --tags` would leak `v0.20.1…`) and
  refuses the development `main` branch. `publish-public.sh --no-tag` is a sync's only push path,
  and `--status` prints the synced high-water mark beside the newest released tag.
* first sync, `dac1c2f` at dev `v0.19.16`: the default branch's `pyproject` now names the tree it
  contains (`0.19.16`), the inversion is gone, and the publication markers still read `v0.19.0` /
  PyPI `0.19.0` — deliberately.
* bookkeeping on the development line: the two releases that had shipped untagged got their tags
  (`v0.19.15` → `3a89ef7`, `v0.19.16` → `a73a95a`), and the stale `github/main` branch was deleted
  after checking it was an ancestor of `master` (so nothing was lost) instead of being left as a
  third public surface.

### Dependencies — and a package that is now an empty shell

`requirements/core.lock.txt` and `dev.lock.txt` refreshed (first refresh since 2026-09-22). Fixes
taken: `certifi` 2026.7.22 → 2026.10.23 (critical), `brotli` 1.2.0 → 1.2.1 (critical), `aiohttp`
3.14.3 → 3.14.5 (high/medium), `multidict` 6.8.0 → 7.2.1 (medium), `setuptools` 84.0.0 → 84.2.1 (low).

**`pymupdf4llm` is now capped `<2`.** The old `>=1.28.0` resolves to `pymupdf4llm 2.0`, uploaded
2026-10-19 as a **904-byte wheel** whose own METADATA reads: *"This is an empty package that is
required by pymupdf-2.x … The pymupdf-2.x package now contains the 4llm code that used to be in
pymupdf4llm-1.x."* Installing it leaves `to_markdown` absent while declaring no dependencies at
all, so the unpinned requirement would have shipped a broken PDF path to anyone installing from
PyPI. Staying on the 1.x line keeps the working extraction path; migrating to `pymupdf>=2` needs
extraction-parity testing on real PDFs and is a roadmap item, not a lock refresh.

Two alerts are **accepted with the blocking condition measured**, not waved through:

* `filelock` — the fix is `4.2.1`, which requires Python `>=3.11` while this package declares
  `>=3.10`; and `litellm 1.106.4` pins `filelock<4.0`, so the resolver lands on `3.32.7` (a
  downgrade from the previous lock's `4.0.0` — litellm's cap, not drift).
* `Twisted` — the only published fix is `26.10.0rc1`, a pre-release; the lock stays on `26.4.0`
  until a final release exists.

Verified: `pytest tests/{test_recut_public,test_gates,test_paths,test_sanitization,test_cron_round}.py`
rc 0; `ruff` and `pyright` clean on the touched files; the judgement matrix exercised end-to-end
(four refusals with their exact messages, plus a clean sync dry run that rolls back); `pre-push`
fed fake refs (`v0.20.3` → reject, `v0.21.0` → pass, `main` → reject, dev remote → pass); and a
**clean venv installed from `requirements/core.lock.txt`** runs `hfpclawer version` → `v0.19.16`
with `pymupdf4llm.to_markdown` callable.

## [2026-10-17] fix | v0.19.16 — `--pick` carried no metadata, so a picked paper was filed as an empty shell

`--pick` exists for the case the axes cannot express: one named paper the round wants in the store.
It handed `ensure_paper` nothing but the id. Measured on 2026-10-17, three picks (`2610.14683`,
`2610.18449`, `2610.18938`) wrote rows with `title=''`, an empty abstract and `year=0` — the store went
1319 → 1322 and every one of the three was invisible to any later query on title or year. That is the
same failure class as the `x`-titled row from round 10 and the nine-day `year=0` record from round 15:
a write path that fills required fields with placeholders is how the empty-title population grew in
the first place.

* `build_idlist_url(ids)` / `fetch_by_ids(ids, pacing)` — the API's `id_list=` form, because
  `search_query=` cannot say "exactly these ids". One request covers every pick in the round.
* `_run` now resolves missing pick metadata **before** the diff. A pick the feed does not return is a
  `UsageError`, not an empty row: an absent paper is recoverable, a placeholder row is not.
* the three measured shells were removed (`remove_paper`, row-level snapshot events) and re-filed by
  the fixed runner with real titles, abstracts and `year=2026`; empty-title rows in the store: 0.

`tests/test_cron_round.py` gains four gates: the id_list URL shape, rejection of an empty/all-blank id
list, an end-to-end `_run` case asserting the picked id reaches `ensure_paper` **with** title,
abstract and year, and a case asserting the run refuses a pick the feed omits.

Verified after the fix: `pytest tests/test_gates.py tests/test_cron_round.py` → **95 passed**,
`ruff check` clean on both touched files, `pyright scripts/cron_round.py` → 0 errors, and the re-run
`--pick 2610.14683 --pick 2610.18449 --pick 2610.18938 --dedup-regression 2610.21233v1` exits 0 with
`dedup_regression [{2610.21233, is_new: false}]` and `duplicated_forms: {}`.

## [2026-10-16] fix | v0.19.15 — the id-form split survived in the write path; the dedup probe forked a duplicate

v0.19.14 normalised identity for the **diff** (`select_new` → `find_stored_form` probes `bare` and
`v1..v9`) and left it unnormalised in the **write**: `ingest_one` passed the bare id straight to
`ensure_paper`. Measured on 2026-10-16, in a round whose purpose was to *detect* a broken dedup path:

```
python3 scripts/cron_round.py --source cron-2026-10-16-round15b --dedup-regression 2610.08691v1
→ VIOLATION: dedup regression failed: 2610.08691 returned is_new=True (expected False)
```

`2610.08691` was filed on 2026-10-07 as `2610.08691v1`; the re-post entered as `2610.08691` and wrote a
second paper row (`title=''`, `year=0`) plus a second identifier — the store went 1316 → 1317, and the
extra row is invisible to `store invariants` for the same reason the `x`-titled row is. The stray row
and the duplicate identifier were removed the same round, with the removal recorded as a row-level
snapshot event.

* `resolve_ingest_id(store, bare)` — ingest now targets the **stored** form when one exists. The probe
  helper was already correct; nothing called it on the write path.
* the year is backfilled whenever the stored record has none, not only on a fresh insert. A first
  insert that arrived without `published` used to stay `year=0` for ever — which is how `2610.08691`
  spent nine days with no year (repaired on 2026-10-16).

`tests/test_cron_round.py` gains five gates: the stored-form resolution, its fallback, the
zero-means-unfilled predicate, and two `ingest_one` cases asserting the id handed to `ensure_paper` is
the stored form and that a `year=0` record is repaired exactly once.

Verified after the fix: the same command exits **0**, `dedup_regression`
`[{arxiv_id: 2610.08691, is_new: false}]`, `duplicated_forms: {}`, `1316 → 1316` papers.

## [2026-10-10] feat | v0.19.14 — every round's ingest from a one-shot script to a reusable runner

Three defects came out of the per-round one-shot scripts (`cron_round_<date>.py`), all measured on
2026-10-10 while reviewing the round-10 loop:

* **the id-form split.** `2610.06986` and `2610.06986v1` are the same paper, but compare unequal
  under exact string matching: a dedup probe written in one form silently missed the other. The
  store ended up holding both forms — a stray row titled `x` sitting beside the real
  `OpenDiscoveryTrace` record for `2609.09203` / `2609.09203v1`.
* **no shared diff.** "Which candidates are new" was recomputed by hand every round, against
  nothing reproducible.
* **a private HTTP client.** One round re-implemented the arXiv call with `CERT_NONE`, skipping TLS
  verification for no benefit; `arxiv_lookup._http_get` already solves the real problem there (the
  `406` edge fingerprint) without weakening TLS.

`scripts/cron_round.py` keeps the round-specific parts as arguments (the axes, the picks, the
regression id) and delegates the rest to existing modules — `arxiv_lookup` for HTTP, pacing and
feed parsing, `paper_store` through its **public methods only** for identity and ingest. Identity
comparison normalises to the bare `YYMM.NNNNN` form, so a stored `vN` variant counts as already
filed; a dedup probe that comes back `is_new=True` fails the run instead of being noticed by hand
three rounds later. `--audit-forms` walks the store for ids held under several forms, which is how
the drift surfaces before it becomes a duplicate paper.

The abstract is taken from the feed alongside `parse_feed`'s rows (that helper returns only
`{id,title,published,categories}`), and `year` is backfilled from `published` because
`ensure_paper` takes no `year` argument — leaving it at 0 is what makes most of this store unusable
for year-based analysis.

`tests/test_cron_round.py` covers the pure logic offline: version/bare normalisation, the query
encoder that must not turn `+` into `%2B`, year extraction, feed/abstract alignment, the store diff
in both form directions, the duplicate-form audit, and the regression predicate.
























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
> **Default branch ≠ release marker (2026-09-22).** The public line is a *snapshot of a release
> tag*: it is cut from the development line's own `vX.Y.Z` (`scripts/recut-public.py`). Between
> aligned cuts — as after the retracted `0.21.0` stamp — the default branch can carry
> development-line content while its `pyproject.toml` still reads `0.19.0`, so **one version number
> can describe two different trees**. This is documented, not force-pushed away: the next aligned
> cut restores the invariant. Until then, reproduce documented behaviour with the **PyPI version**,
> and pin a commit if you need default-branch capabilities.
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

### [2026-09-23] feat | v0.19.8 — title → arXiv ID reverse lookup; `-k source` kind fix

`hfpapers/arxiv_lookup.py` + `hfpclawer lookup-id|lookup-ids`: a paced, reason-carrying path from a
title to an arXiv ID. Encapsulates four measured quirks — HTTPS-only (plain HTTP = 0-byte body),
burst throttling (≥40 calls → 0-byte; `Pacing` keeps ≥3s + escalating backoff), `quote()` mangling
`+`→`%2B`, and a **client fingerprint** (same URL: 406 for `urllib`, 200 for `requests`) so
`_http_get` tries `requests` first. Acceptance = equality → containment (≥3 words) → ratio ≥ 0.60,
because the closest title can be a *different* paper. Reasons: `exact|prefix|ratio|below-threshold|
no-candidate|blocked` (see `docs/ARXIV_LOOKUP.md`).

Also fixes the streamed/sink payload check: `/src/` may return the rendered PDF, and the sink branch
only sampled the tail for NUL bytes, so `fetch <id> -k source` reported success on a 5.2MB PDF
(measured). The head is now checked and every rejection states its reason in `error`.

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
