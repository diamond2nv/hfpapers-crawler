# CHANGELOG

<!-- changelog-window rule="bytes<=24576" kept=13 of=15 bytes=23821 rotated=2026-09-17 -->











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
