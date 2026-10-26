# CHANGELOG

<!-- changelog-window rule="bytes<=24576" kept=9 of=10 bytes=21455 rotated=2026-10-17 -->

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

## [2026-10-05] fix | v0.19.13 — a Crossref title search may not return a stranger

> Crossref's `/works?query=<title>` is a fuzzy search: it matches on shared words, so its top hit for
> an arXiv paper can be an unrelated work. `cross_verify` accepted any hit scoring ≥ 0.3 and handed it
> back with confidence `sim + 0.2`. Importing arXiv 2607.27201 ("Mental World Modeling") attached
> `10.1007/978-1-4939-6616-5_3` ("Science of Mental Modeling", a 2017 Springer chapter) and stamped
> `year=2017 · venue='Mental Modeling Approach'` onto a 2026 preprint — a stranger at similarity 0.387
> whose boosted confidence (0.587) sat just under the 0.6 gate, so the class recurred whenever the
> bonus cleared it (a live record still held "SSCAP…" as the DOI of a "ConsensusTAS…" paper, 0.404 →
> 0.604).

- **M** `CrossrefClient.MIN_TITLE_SIMILARITY = 0.5` + a floor in `cross_verify` — a title-search hit is
  returned only when its trigram-Jaccard similarity clears the bar, and a below-bar near-miss is logged
  with both titles and its score instead of being handed to a caller. The bar is the same one the
  supplied-DOI path already uses (`PaperStore.SUPPLIED_DOI_MIN_SIMILARITY`), measured the same way: of
  57 live Crossref attachments, the floor newly rejects exactly the one known-wrong match and keeps the
  other 56; every genuine match scores ≥ 0.5.
- **Tests** — `tests/test_crossref_title_gate.py` (5): the polluted instance (real captured hit list)
  yields no candidate and `ensure_paper` writes neither the DOI nor its venue/year; a genuine match is
  still attached with its venue; the floor boundary is asserted against the real similarity function.

## [2026-09-25] fix | v0.19.12 — a duplicate pair is judged by its DOIs, not by its identifier count

> `store dedup` and the audit both classified duplicates by identifier *kinds*: one copy with the DOI
> and one with the arXiv id → merge; overlapping kinds → "two artefacts of one work, leave it". The live
> store had a pair where both copies held a DOI and one of them described a *different paper* — the
> heuristic then protected the wrong copy from removal.

- **A** `invariants.classify_duplicate_pair` / `plan_duplicate_group` — evidence-first ranking (a record
  whose DOI describes its own title outranks one with none, which outranks one whose DOI describes
  another paper) and four verdicts: `mergeable`, `version_pair` (both DOIs describe the title — journal
  paper plus report, both kept), `drop_wrong_doi` (culprit named; its DOI is discarded, never moved),
  `human`.
- **M** `store dedup [--network]` — verdicts from that shared classifier, and the table names what the
  drop candidate's DOI actually points at; `--apply` acts on `mergeable` and `drop_wrong_doi` only.
  Offline it behaves exactly as before.
- **M** `store invariants --network` — duplicate findings are re-judged: a version pair becomes
  `record.version_pair` at `info` severity, so a legitimate pair stops being reported as a defect.
- **A** write-path guard — `ensure_paper` returns the existing record for an identifier-less arrival
  whose title is already filed (`identity_reused` event). That is how both live pairs came to exist: an
  ORCID batch carrying DOIs, then a second pass over the same works without them.
- **Tests** — `tests/test_duplicate_verdicts.py` (15, network stubbed).

## [2026-09-25] fix | v0.19.11 — the supplied-DOI bar, measured rather than guessed

> 0.19.10 shipped 0.4 because that is what the automatic path effectively applies. The store says a
> higher bar costs nothing: of the 310 DOI↔title pairs the full audit called correct, **none** scores
> below 0.45, and two below 0.5.

- **M** `PaperStore.SUPPLIED_DOI_MIN_SIMILARITY` 0.4 → **0.5**. The same-field near-neighbour the gate
  exists for (`10.2172/839535`, a *different* OSTI report: 0.44) is now refused; the two format
  variants under 0.5 (all-caps 1990s AIP titles against Crossref's modern form) go to review rather
  than being written at 1.0, and a deliberate `accepted-unverified` still admits them.
- **Tests** — both directions pinned in `tests/test_doi_write_gate.py`.

## [2026-09-25] fix | v0.19.10 — a supplied DOI is looked up before it is written

> 0.19.7 closed the DOI the store *finds itself*; this closes the DOI it is *given*. `add_identifier`
> wrote such a DOI at the default `confidence=1.0` with no lookup — and every wrong DOI in the
> 2026-09-25 full audit (3 of 341) arrived that way, one registered nowhere.

- **A** `hfpapers/doi_registry.py` — `resolve(doi)` → `ok | not_found | error`, Crossref first and
  **DataCite second**: a Crossref 404 is not a bogus DOI (arXiv/Zenodo/CNKI DOIs live there) —
  "could not check" is not "wrong".
- **A** `PaperStore.attach_supplied_doi()` — unregistered or title-mismatched → **refused** +
  `identifier_rejected`; otherwise written with an `identifier_unverified` event if it could not be
  checked (unreachable registry, no title, cross-language). A verified DOI keeps `confidence=1.0`,
  which now means *verified*, not *assumed*. Known-bad rows: the unregistered and 0.06-similarity DOIs
  are refused; the 0.44 near-neighbour still passes, its similarity recorded on the attach event.
- **M** `ensure_paper(..., verify_doi=True)` routes supplied DOIs through the gate; `verify_doi=False`
  keeps an offline batch working.
- **A** tail check — `check_store(only_sf_ids=…)` in `StorePipeline.close_spider` and `hfpclawer
  import`, so a batch reports its own defects in the run that created them.

## [2026-09-25] fix | v0.19.9 — the DOI title check stops calling correct DOIs wrong

> Two audits of the live store agreed on a wrong conclusion: `_norm` spent its 80-character budget on
> Crossref's inline MathML, and CJK-against-English pairs scored 0.00.

- **M** `hfpapers/invariants_network.py` — strip `<...>`/entities, NFKC-normalise, *then* fold case.
  `10.1103/PhysRevLett.89.125003`: **0.165 → 0.957** (β mid-title; `[:80]` never rescued it — the same
  defect deleted a correct DOI in a peer's audit). `is_cross_language()` now counts
  CJK-against-English pairs instead of scoring them (two 《物理学报》 records: **0.00**), exposed as
  `coverage["doi_title_cross_language"]`.
- **Tests** — `tests/test_invariants_network.py`: normalisation, both cross-language directions, and
  guards that real mismatches still report while unreachable DOIs still count.
- **Scope** — dev line only; PyPI gets it with `0.21.0`.
