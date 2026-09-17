# CHANGELOG

<!-- changelog-window rule="bytes<=24576" kept=10 of=11 bytes=22601 rotated=2026-09-17 -->














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

## [2026-09-17] release | v0.19.0 — first PyPI release of the 0.18 line (with dependency tiering)

> `pip install hfpclawer` has served **0.17.0** since 2026-09-05: none of the 0.18 work — the
> biomedical sources, the verification state machine, the private-config overlay, the
> install-safe state paths — and it still wrote its database into `site-packages`. This
> release closes that gap. `0.19.0` keeps the project's PyPI rule (`0.x.0`, odd `x`).

- **the 0.18 line, delivered**: Europe PMC / bioRxiv / medRxiv behind one source registry,
  `pending → verified / stale / suspect` state with symbolic 0-LLM conflict detection,
  recommendations from first-party signals only, `config.local.yaml` overlay, dateless/
  DOI-only dedup that keeps records, shared retry policy, changelog coverage and window
  gates, the doc-surface audit, and state that resolves to the user's directories once
  installed instead of into `site-packages`.

### Core install slimmed: 13 dependencies → 11

- **M** `spacy` moved from core to the `nlp` extra; `pyzotero` moved to a new `zotero`
  extra. Both are imported lazily behind guards (`hfpapers/nlp` catches `ImportError`,
  `hfpclawer/zotero` uses `HAS_PYZOTERO`), so nothing breaks by their absence.
- **M** absence is now visible instead of silent: no spaCy → one warning naming
  `pip install "hfpclawer[nlp]"`; no model — the *expected* state on PyPI, which will not
  host the direct-URL model wheel — names `python -m spacy download en_core_web_md`; the
  Zotero guard names `pip install "hfpclawer[zotero]"`.
- **verified** on a core-only install: 35 packages, no spaCy/pyzotero, `hfpclawer version`
  and `store status` work, both hints fire as intended.

### Dependency auditing became possible

- **M** `requirements/` — three stale hand-copied lists removed: `requirements_core.txt` and
  `requirements_dev.txt` (May mirrors of `pyproject.toml` that had drifted) plus
  `requirements_all_0.1.3.txt`, a 188-line freeze of the **v0.1.3** environment that a
  scanner reviews as if it were today's dependency set. Replaced by generated locks —
  `requirements/core.lock.txt` and `requirements/dev.lock.txt` (`uv pip compile
  pyproject.toml …`), each with a "do not edit" header and its regeneration command.
- **M** `pyproject.toml` — `dev` in both definitions now pulls `hfpclawer[nlp]` and
  `hfpclawer[zotero]`, so a dev environment still has every test dependency.

## [2026-09-17] release | v0.17.3 — public snapshot of the 0.18 line

- **Public line** (`0.17.x`, its own sequence): public cut of the development line's `0.18.0` – `0.18.22` work: Europe PMC / bioRxiv / medRxiv
  behind one source registry, the verification status machine, recommendations from local signals,
  install-safe state resolution (XDG user directories instead of `site-packages`), changelog
  coverage/window gates, the doc-surface audit, and the restructured documentation (README five
  feature points, `docs/FEATURES.md`, light root pages).
- **Sanitization coverage widened**: alongside sensitive values (real ORCIDs, LAN IPs, machine
  codenames, personal emails, tokens) the gate now rejects internal **layout and project names** —
  local directory layouts, private sibling repository names, internal wiki/mirror hosts. The older
  patterns could not see that class (`/home/[a-z]+` cannot match `~/`); peer repositories are
  declared through the environment instead of being hard-coded.
- `scripts/sanitize-patterns.sh` is the single definition, read by the git hook, the public-release
  script and `tests/test_sanitization.py`.

- **note** — the public line's earlier recuts (`v0.17.0` – `v0.17.2`) stay in the
  [public-line section](#public-line--sanitized-recuts) below; the guard needs a top-level entry, so
  public releases are recorded here too.

## [2026-09-17] fix | v0.18.22 — install-safe state paths, and the sanitization gate learns the layout class

> The public-install defect recorded in v0.18.21: `hfpclawer` resolved its data directory as
> `Path(__file__).parent.parent / "data"`. In a checkout that is the repository root and everything
> works; installed from a wheel it is `site-packages`, so `hfpclawer store status` created
> `<site-packages>/data/papers.db`. Read-only or system-wide installs fail outright, the library
> disappears with the environment, and nothing tells the user where their data went.

- **A** `hfpapers/paths.py` — one resolver, two modes: the repository when the package sits in a
  checkout (a `pyproject.toml` beside it, not under `site-packages`/`dist-packages`, writable);
  otherwise the platform user directories (`$XDG_DATA_HOME/hfpclawer` → `~/.local/share/hfpclawer`
  for data/logs, `$XDG_CONFIG_HOME/hfpclawer` → `~/.config/hfpclawer` for config/`.env`).
  `HFPCLAWER_STATE_DIR` / `HFPCLAWER_CONFIG_DIR` override outright; `HFPAPERS_DATA_DIR` still wins
  for the database. Checkout behaviour is byte-identical to before.
- **M** ~25 call sites migrated (`config`, `settings`, `paper_store`, `cli`, `logger`, `evolved`,
  `pool`, `pipelines`, `download_queue`, `search_queue`, `enrich_entities`, `arxiv_search`,
  `arxiv_transport`, `tex_converter`, `fix_entity_map`, `graph/stepping`, `hfpclawer/download/*`,
  `hfpclawer/cli_cron`, `hfpclawer/zotero/cli`); `hfpapers/__init__.py` reads `pyproject.toml`
  through the checkout check and no longer touches the install directory.
- **A** `tests/test_paths.py` — F05 `InstallPathGate` (installed mode resolves under XDG; the
  containment invariant: never inside the installation, even with a stray `pyproject.toml`) and F06
  `NoAdHocStatePathGate` (a source scan fails any new `Path(__file__).parent.parent` state path —
  the defect returned three times through new call sites, so it is gated, not remembered).
- **M** `DEPLOY.md` (state root + per-mode paths), `AGENTS.md` (state-path rule in Repo Standards),
  `docs/DEVELOPMENT.md` + zh (F05/F06 in the gate list).

### The same pass found a gate blind spot, and it is now closed

- **A** `scripts/sanitize-patterns.sh` — the sanitization patterns in one place, read by `pre-push`,
  `publish-public.sh` *and* `tests/test_sanitization.py` (F07), so tightening a pattern cannot miss a
  consumer. Two classes with different severities: **sensitive values** (real ORCIDs, LAN IPs, machine
  codenames, personal emails, tokens — documented/implemented files stay exempt) and **internal layout
  and project names** (local directory layout, private sibling repository names, internal wiki/mirror
  hosts — only the gate scripts themselves are exempt).
- **why** — the old patterns could not see the second class: `/home/[a-z]+` cannot match `~/`, so
  a home-directory path into a private sibling project and the sibling project names sat in code, docstrings
  and the currently published `public` branch. Running the extended gate against that branch flags 20+
  lines, including two in its `PLAN.md`/`ROADMAP.md` that no earlier review had found.
- **M** peer repositories became configuration: `hfpapers.paths.peer_repo()` / `peer_roots()` read
  `HFPCLAWER_PEER_REPOS` (or `HFPCLAWER_PEER_<TAG>`), and the callers that used to hard-code a home
  layout now ask for a declared peer — `hfpclawer graph ingest`, `graph ingest-citations`,
  `hfpclawer audit traceability` (bib detection), `cli_cron` project detection, the Zotero PDF
  fallback (`state_root()`), and `scripts/cron-multi-repo-arxiv-fetch.py` (map from env or the
  gitignored `scripts/cron-repos.local.json`, with a committed `cron-repos.example.json`). Real values
  are in gitignored files; `_detect_repo_name()` no longer guesses identities from directory markers.
- **M** docs neutralised: `AGENTS.md` (layout block, `<lan-wiki>`), `docs/ROADMAP.md` (NAS wiki link,
  the peer-repo diagram label), `docs/use/verify-guide.md` + zh (project names → "private downstream
  projects"), `hfpapers/graph/__init__.py` docstrings.
- **M** `.gitignore` — `scripts/cron-repos.local.json`.

- **note** — the fix is what the pyproject readiness pass found, not a side quest: an install-time
  write into the installation is a defect a public release would ship; so is publishing the
  names of the private projects next to this one.

## [2026-09-17] chore | v0.18.21 — pyproject public-release hygiene, and what the install test found

> A public-push readiness pass: build the artifact, install it into a clean environment, and read
> the metadata a PyPI/GitHub user will actually see. Three small defects, one real one.

- **M** `pyproject.toml` — `Changelog` URL pointed at `blob/main/`, but the public repo's default
  branch is `master` (broken link for every visitor); `[dependency-groups] dev` asked for
  `geopy[graph]`, and geopy provides no `graph` extra (`dev`, `dev-lint`, `dev-test`, `dev-docs`,
  `aiohttp`, `requests`, `timezone` only) — a silent no-op, now `hfpclawer[graph]`; license metadata
  moved to PEP 639 (`license = "MIT"` + `license-files = ["LICENSE"]`, build requires
  `setuptools>=77`), dropping the deprecated `License :: OSI Approved :: MIT License` classifier. The
  built wheel now carries `License-Expression: MIT` and ships `LICENSE`.
- **note (known issue, public install)** — installing the wheel and running
  `hfpclawer store status` from an arbitrary directory creates
  `<site-packages>/data/papers.db`: the package resolves its data directory as
  `Path(__file__).parent.parent / "data"`, which is the repo root in a checkout but the install
  directory once installed. Reproduced in a clean venv (delete the directory, re-run, it returns).
  Harmless for checkout users, wrong for anyone installing from PyPI — read-only or system-wide
  installs will fail, and library state hides inside the environment. Fix design (checkout dir when
  present, else XDG user dirs) is next, as it touches every data-path resolution.

## [2026-09-17] docs | v0.18.20 — root CHANGELOG.md becomes a version-line summary

> The root `CHANGELOG.md` was only a pointer, and the repository has **90 tags across 17 version
> lines** with per-release entries starting at v0.9.13 — so "how did this evolve?" had no answer
> outside git archaeology.

- **M** `CHANGELOG.md` (root) — line-level summary: one row per `0.x` line (0.2 → 0.18) with period,
  theme and what it delivered, plus the release rules in force. Coverage is stated honestly: rows
  before v0.9.13 are **reconstructed from commit history**, entries are contemporaneous from v0.9.13
  on; the detail stays in `docs/CHANGELOG.md` (window) and `docs/CHANGELOG-archive.md`.
- **M** `AGENTS.md` — the Repo Standards table still promised `release.sh VERSION --push`, which
  targets the internal GitLab rather than NAS; corrected to the actual two-step flow.
- **note** — root changelog stays English-only, matching the rule already declared for the
  changelog surface.

## [2026-09-17] docs | v0.18.19 — README keeps five feature points, the detail moves to docs/FEATURES.md

> Twelve feature bullets in the README had grown into a wall of prose whose "readability" cost is
> paid on every visit. The README now states five capabilities, each one sentence and one link; the
> evidence, caveats and cross-references live in a page of their own.

- **M** `README.md` — features reduced to five points (Discovery · Verification · Recommendations ·
  Private stays private · Agent-first and cheap by default), each linking into the detail page;
  `## Links` gained the feature-detail entry.
- **A** `docs/FEATURES.md` — the detail: per capability, what shipped (with versions), the
  guard-rails and the deliberate non-goals, cross-linked to USAGE / ARCHITECTURE / paper_store /
  verify-guide / AGENTS / ROADMAP.
- **A** `docs/cn/FEATURES.zh-CN.md` — line-aligned Chinese mirror (52/52), as the doc convention
  requires; `docs/cn/README.zh-CN.md` mirrors the same five points.

## [2026-09-17] docs | v0.18.18 — root docs become light summaries (function + agent first)

> The four root-level markdown files were either stale by ~100 releases (`PLAN.md`, `ROADMAP.md`
> still described the v0.6.x era of 2026-06-28) or written as an operator transcript (`DEPLOY.md`).
> They are now short, function-first summaries that point at `docs/` for detail — the root is a
> front page, not an archive.

- **M** `ROADMAP.md` — rewritten as a light roadmap: what the project is for, the version line, the
  current `0.18.x` working set as a status table, a short "next", and the non-goals *corrected*
  (paper recommendation is no longer a non-goal — it shipped; the Scrapy/Redis queue design still
  is not implemented). The v0.6.x-era text stays in git.
- **M** `PLAN.md` — rewritten as a one-screen summary: the five functions (find / fetch / verify /
  store / serve) and how to work in the repo agent-first (CLI first, deterministic by default,
  nothing personal in tracked files, gates over discipline, no hard-coded paths).
- **M** `DEPLOY.md` — de-transcribed: requirements, install (`hfpclawer[pdf,quic]`), a smoke test an
  agent can run (`source-list` / `fetch` / `store status` / `check-new`), where data lives, and the
  actual LAN shape (independent nodes sharing only the dedup file). The never-implemented
  scrapy-redis path is marked as such instead of being presented as a deployment option.
- **A** `CHANGELOG.md` (root) — a pointer to `docs/CHANGELOG.md`, since the conventional root path
  otherwise resolves to nothing.
- **note** — root docs reference no hard-coded machine paths, and the doc audit
  (`scripts/doc_audit.py`) now covers them: every command and path they mention is checked.
