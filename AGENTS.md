# hfpapers-clawler — AI Agent Development Guide

This file is for AI coding assistants (Hermes Agent, OpenCode, Claude Code, etc.)
working on this project. It describes the project structure, key patterns, pitfalls, and constraints.

## Quick Navigation

```
<checkout>/hfpapers-crawler/          ← canonical checkout
└── any LAN mirror path → symlink → the checkout above (see .hermes/internal-guide.md)
├── hfpapers/             # Main Python package
├── hfpclawer/            # Download pipeline (OAI-PMH, Kaggle, monitor)
├── hfpapers/paths.py     # state-location resolver (checkout → else XDG user dirs)
├── tests/                # pytest tests: test_paths + test_sanitization are gates (F05-F07)
├── scripts/              # Gates, tooling and publishing:
│   ├── sanitize-patterns.sh   # the sanitization patterns — single source (hook + publish + F07)
│   ├── changelog_guard.py     # "is this version documented?" (release.sh + F03)
│   ├── changelog_rotate.py    # bounded changelog window, archive, --verify-history (F04)
│   ├── doc_audit.py           # advisory doc-surface audit (C1-C7)
│   ├── recut-public.py        # cut a public release: gates + tag + push, dry run by default
│   └── pre-push               # the installed git hook (version + sanitization gates)
├── requirements/*.lock.txt # generated locks (`uv pip compile`) — the audit target, never edited
├── docs/                 # English documentation
│   └── cn/               # 中文文档 (Chinese docs, line-aligned)
├── config.yaml           # Main config — structure only; real values in config.local.yaml
├── config.local.yaml     # gitignored overlay, deep-merged over config.yaml
├── pyproject.toml        # Package config (setuptools) + the single version source
├── run.sh                # One-click pipeline runner
├── AGENTS.md             # ← This file
└── .gitignore
```

## Repo Standards

| PEP | Rule | How |
|-----|------|-----|
| 621 | **Version source** | `pyproject.toml` only; `__init__.py` reads the local `pyproject.toml` first (regex), with `importlib.metadata` as the installed-wheel fallback — metadata alone goes stale in a checkout |
| — | **Commit message version** | `v0.{x}.{y}: 描述`. 版本号**必须来自 pyproject.toml**，禁止自行编撰（如 commit msg 写 v0.13.x 但 toml 是 0.12.x）。hotfix 按最新 tag 系列递增 |
| 660 | **Editable install** | `pip install -e .` must work (has `[build-system]`) |
| 8 | **Code style** | ruff (100 chars, double quotes); 100% English in .py |
| — | **.gitignore** | Must cover: `__pycache__/ *.egg-info/ dist/ build/ .venv/ .env` |
| — | **State paths** | Resolve through `hfpapers/paths.py` only: the repository in a checkout, XDG user dirs (`~/.local/share/hfpclawer`, `~/.config/hfpclawer`) once installed — never `Path(__file__).parent.parent`, which is `site-packages` in a wheel. Enforced by gate F06 (`tests/test_paths.py`) |
| — | **Version mgmt** | `bash scripts/release.sh VERSION` (bumps pyproject, commits, runs the changelog gates); push with `git push forgejo vX.Y.Z && git push forgejo main` — never `--push`, which targets the internal GitLab. alignment=hotfix, no force tag |

> Templates and installer: `~/.hermes/skills/software-development/version-management/`

## Public-Release Sanitization (MANDATORY)

> ⛔ **One public remote** — `github` (github.com/diamond2nv, default branch
> `master`) — and the repo is published to PyPI. Anything committed to a branch
> that reaches it becomes public.
>
> `forgejo` (NAS) and `origin` (lab GitLab) are **private**. `mirror` (Aliyun
> Codeup) is **semi-public**: it is a *private repo cloud backup*, not a public
> host — but it is not a private channel either, so treat it as off-limits for
> real secrets. Push sensitive changes to `forgejo` only.
>
> ⚠️ Remote names: in this working copy the NAS remote is **`forgejo`** (older
> revisions of this file called it `local`) and `origin` is the lab's internal
> GitLab, **not** a public host. Run `git remote -v` before trusting a name.

### What must NEVER appear in tracked files

| Category | Rule | Example placeholder |
|----------|------|---------------------|
| Private LAN IPs | `192.168.0.x`, `10.x`, `172.16-31.x` | `<windows-host-lan-ip>` / `<lan-wiki>` |
| Zotero user_id | Real local API user id | see `.hermes/internal-guide.md` |
| Real person names | Real researcher/owner names in examples/docs | `Jane Doe` / `张三` / `HFPClawer Maintainers` |
| ORCID iDs | Real ORCIDs — they identify an individual | `0000-0002-1825-0097` (ORCID's own spec example) |
| Personal emails | `*@example.com` must not carry real usernames | `dev@example.com` |
| Machine home paths | `/home/<real-user>/...` | `os.path.expanduser("~/.local/...")` |
| Internal machine codenames | HUAWEI / Speaker / WSL hostnames in public docs | generic "LAN peers" |

### Rules

1. **Examples use neutral names**: docstrings/schema examples → `Jane Doe`,
   `Smith, John`, `张三` — never real researchers or the repo owner's name.
2. **Real values live in `.hermes/internal-guide.md`** (gitignored, LAN-only) —
   placeholders in tracked files point there.
3. **Peer repositories are environment data, never constants**: a private
   sibling project is addressed by tag through `HFPCLAWER_PEER_REPOS`
   (`{"tag": "/path"}`) or `HFPCLAWER_REPO_MAP`, and the real values live in
   `.env` / `scripts/cron-repos.local.json` (both gitignored). Hard-coded
   home-directory paths that point into a private sibling project, and the
   sibling project names themselves, must not appear in code, docstrings or docs
   (the exact shapes are in `scripts/sanitize-patterns.sh`) — gate F07
   (`tests/test_sanitization.py` + `scripts/sanitize-patterns.sh`) fails them.
4. **Config files with real identity**: `scripts/researcher-audit/people.yaml`
   is gitignored (real scholars + Google Scholar IDs); the tracked file is
   `people.example.yaml` with `<placeholder>` entries. The same pattern now
   covers `config.local.yaml` (gitignored, deep-merged over `config.yaml` by
   `hfpapers.config.load_config`): the tracked `config.yaml` keeps only the
   structure (`stepping.layers: []`, `search.biomed_queries: []`) while the real
   author lists, ORCIDs and tracked research directions live in the local overlay.
5. **pyproject.toml `authors` is the maintainer's public attribution** — keep
   the real name there (it is intentional public authorship, not a leak).
6. **User-Agent strings** must use `dev@example.com` unless a real public
   contact is intended.
7. **Before pushing `master` to `github` or releasing**: run
   `bash scripts/publish-public.sh --check` (read-only), or `python3 scripts/recut-public.py
   --version X.Y.Z` for a full cut with its gates.

   The patterns live in **`scripts/sanitize-patterns.sh`** — single source, read by the git hook,
   the publish script and `tests/test_sanitization.py` (F07), so tightening a pattern cannot miss a
   consumer. Two classes, two severities:

   - **sensitive values** — real ORCIDs, LAN IPs, machine codenames, personal emails, tokens.
     Files that document or implement the rules are exempt (a rule must be able to name what it
     bans), so read the residual hits rather than counting them: this file, the approved
     placeholders, the "Replace with A's IP" examples in the deploy docs, and the
     platform-detection code in `hfpclawer/zotero`.
   - **internal layout and project names** — local directory layouts, private sibling repository
     names, internal wiki/mirror hosts. Only the gate scripts themselves are exempt; there is no
     other back door, because this is the class a reviewer is least likely to notice.

   Two lessons, both paid for:

   - **A missing category is worse than a missing check** (2026-09-11). The ORCID pattern did not
     exist, so real ORCIDs sat in tracked files while a narrower command reported clean — a check
     that cannot see what it exists to protect grants false confidence. `0000-0002-1825-0097` is
     ORCID's own spec example and is the approved placeholder.
   - **`/home/[a-z]+` cannot see `~/`** (2026-09-17). Hard-coded home-directory paths pointing into a private sibling
     project, and the sibling project names themselves, passed the gate while sitting in package code,
     docstrings and one published branch. Peer repositories are environment data now (rule 3), and
     the class is gated.

8. **Commit messages are public too**: never put real person names, ORCIDs,
   private IPs, or internal emails in commit messages (subject or body). Use
   neutral wording
   ("fix division-by-zero in researcher audit", not names). Rewrite with
   `git commit --amend` before pushing to a public remote if a sensitive name
   slipped in.
9. **Commit hygiene**: sensitive-only changes → push to `forgejo` (NAS), not to a
   public remote. Public release is a separate, deliberate step.
10. **Two lineages, aligned version numbers** — the public repository carries the same versions
    PyPI does. PyPI accepts only `0.x.0` with an **odd** `x` (0.19.0, 0.21.0, …) for this project,
    so that is what a public release uses; the older `0.17.x` public sequence is retired, and
    development-line fix releases such as `0.19.1` stay private bookkeeping, folded into the next
    aligned release.

    | Branch | Lineage | Tracks | Release with |
    |--------|---------|--------|--------------|
    | `main` | development line | `forgejo/main` | `bash scripts/release.sh VERSION`, then `git push forgejo vX.Y.Z && git push forgejo main` |
    | `public` | public line, PyPI's numbers | `github/master` | `python3 scripts/recut-public.py --version X.Y.Z --push` |

    `recut-public.py` lays a sanitized snapshot in a scratch worktree, sets the version **after**
    the sync (the sync reverts it), commits as the public identity, runs the three gates
    (changelog coverage, sanitization, snapshot tests) and only then pushes — a dry run by default,
    refusing a version PyPI could not carry or one not above the current public tag. Never
    `git push github master`: that resolves to a **local** branch named `master` rather than to your
    work (the script uses the explicit refspec `public:master`). **No force-push** — history is
    appended to.

    **Tag namespaces.** Alignment means one version number has two commits — the public snapshot
    and the development commit — while a repository's tag namespace is shared. So the public tag
    exists locally under the namespaced name **`public-vX.Y.Z`** and is pushed with an explicit
    refspec onto the real name on the remote:
    `git push github refs/tags/public-vX.Y.Z:refs/tags/vX.Y.Z`. The development line's own
    `vX.Y.Z` is therefore never moved, and the refusal to move a published tag stays honest.
    Consequence: `git fetch --tags github` in this checkout collides on those names — verify with
    `git ls-remote` instead (as `recut-public.py` does). `publish-public.sh` implements all of
    this; `v0.19.0` on `github` is the public snapshot, on `forgejo` the development commit.

    **One tag per published version.** The public line's tag set *is* its release surface —
    odd `0.x.0` only, the same name as its GitHub Release — so consecutive public tags skip the
    private even lines by design (`0.15 → 0.17 → 0.19 → 0.21`). Patch-level continuity is the
    development line's job (`v0.19.0 … v0.19.6` on `forgejo`/NAS). Never add even-`x` tags to
    the public line for appearance: `recut-public.py` refuses a version PyPI could not carry,
    and a public tag without a release invents a numbering story nothing else follows.

11. **Only the maintainer's primary machine is authorized to publish**: of the
    machines on this LAN, only that one holds GitHub credentials. The others push
    to NAS, and the primary machine reviews before anything is published. Failing
    at the push step elsewhere is expected behaviour, not a broken setup — do not
    go hunting for credentials on an unauthorized machine.

## Environment & Connectivity

Zotero local API runs on localhost:23119 (both machines). See `.hermes/internal-guide.md` for machine-specific details (WSL IPs, GPU/CPU tables).

### Zotero LAN Access (WSL Windows-side, 2026-08-16)

WSL's Windows-host Zotero can be shared to LAN peers via netsh portproxy (listen 0.0.0.0:<LAN_PORT> → 127.0.0.1:23119). LAN peers can query it without running Zotero locally:

- Endpoint: `http://<windows-host-lan-ip>:<LAN_PORT>/api/` (Zotero 9.0.6; user_id and item count: see `.hermes/internal-guide.md`)
- **Must send `Host: localhost:23119` header** (Zotero 9+ validates Host) + `Zotero-API-Version: 3`
- Firewall allows only RFC1918 private ranges — no public access
- `connectors/ping` returns 404 "No endpoint found" on 9.x — use `/api/users/0/items?limit=1` to verify
- Full docs: wiki `concepts/zotero-integration-research.md` §局域网接入; skill `zotero-local-api` 场景 C

### Zotero UA Constraint

Zotero local API rejects `Mozilla/5.0` User-Agent (403). pyzotero's default urllib UA works fine.

### spaCy NLP (hfpapers.nlp subpackage)

Available when `hfpclawer[nlp]` is installed (`uv sync --extra nlp`):
- `en_core_web_md` model (~45MB) with word vectors for semantic similarity
- Falls back gracefully to regex-based extraction when spaCy unavailable
- Used by: title keyword extraction, semantic reranking, innovation point extraction, auto-tag generation, TF-IDF tag analysis

## Core Architecture

### 3-Tier Storage

| Tier | Location | Purpose | Persistence |
|------|----------|---------|-------------|
| SQLite | `data/papers.db` | Primary store (3 tables) | Persistent |
| JSON | `data/candidates_latest.json` | Fast query cache | Overwrite |
| Files | `pdfs/` `mds/` | Download results | Persistent |

### Key Data Flow

```
HF CLI → arXiv verify → Keyword classify → Dedup → paper_store (SQLite)
                                                      ↓
                                              PDF download → MD convert
```

### Module Dependency Chain

```
sources.py       — Multi-source search (HF/OpenReview/PwC/arXiv)
       ↓
paper_store.py   — SQLite store (Snowflake + Crossref)
       ↓
evolved.py       — Crawl engine (HFPapersCrawler / DedupEngine / PaperDownloader)
       ↓
cli.py           — Typer CLI (10+ subcommands)
mcp_server.py    — MCP Server (7 tools)
```

### Config Loading

```python
from hfpapers.config import load_config, get

cfg = load_config()            # Load YAML + .env
val = get("search.queries")    # Dot-separated access
```

Config search order: `config.yaml` → `.env` (env only overrides API keys)

### Global Singletons

`paper_store.py` exposes high-level interfaces:

```python
from hfpapers.paper_store import get_store, get_crossref, ensure_paper, store_stats

store = get_store()          # PaperStore singleton
cr = get_crossref()          # CrossrefClient singleton
sf_id, is_new = ensure_paper(arxiv_id, title, ...)  # Write + dedup + cross-verify
stats = store_stats()        # Statistics
```

## Development Commands

```bash
source venv/bin/activate    # Must activate
ruff format .               # Format (line-length=100, double quotes)
ruff check .                # Lint
pyright .                   # Type check
python -m pytest tests/ -v  # Run tests
python -m build             # Build package
```

## Testing Guidelines

### Provided Fixtures

`tests/conftest.py` provides:
- `test_env` — auto-isolated temp directory + minimal config.yaml
- `paper_store` — in-memory SQLite PaperStore instance

### Test Strategy

| Category | Coverage | External Dependencies |
|----------|----------|----------------------|
| Unit | paper_store CRUD, Snowflake, config | None |
| Unit | DedupEngine, RelevanceDetector | None |
| Unit | HardwareProbe | psutil |
| Integration | paper_store ↔ SQLite | SQLite |
| Integration | sources search | Mock |

Creating new tests:
1. `tests/test_<module>.py`
2. Use `test_env` fixture for environment isolation
3. Mock network requests (requests / subprocess)
4. Don't depend on external API responses

> ⚠️ **`scripts/publish.sh` bypass**: it refuses to run when the tree is dirty, so the
> direct-url strip (step 1 above) has to be done by hand: `python -m build` +
> `python /tmp/twine_v4.py upload …`, then `git checkout pyproject.toml`. See the
> `pypi-publish` skill.

> ⚠️ **Release discipline**: `scripts/release.sh` is the development line's single entry
> (version source = `pyproject.toml`). Do **not** pass `--push` — it targets `origin`, the
> internal GitLab; push the NAS yourself, tag before branch:
> `git push forgejo vX.Y.Z && git push forgejo main`. `scripts/pre-push` is two gates:
> ① version consistency, for `refs/heads/main` only (the public line carries its own state);
> ② sanitization, for every push, covering both the sensitive-value class and the internal
> layout / project-name class. Install and verify with
> `cp scripts/pre-push .git/hooks/pre-push && diff -q scripts/pre-push .git/hooks/pre-push`.
> The three changelog gates (entry exists / window budget / no entry lost) live in
> `release.sh`. A public release is a *separate*, aligned step: `scripts/recut-public.py`
> (rule 10).

### Testing Before Release

- `ruff check` must be clean **for the files you touched** — the repository still carries
  pre-existing lint in legacy scripts and tests, so a whole-tree count is not the signal.
- `pytest tests/` must be green: the default run is the deterministic set (see the gate
  inventory below); environment-heavy classes are opt-in via markers.
- `pyright` warnings about missing imports (torch, scrapy, sentence_transformers) are
  acceptable — those are optional dependencies.
- A red test that predates your change still needs a verdict: fix it, mark it, or record it.
  "It was already failing" is a finding, not a dismissal.

### Test entry points and the gate inventory

`pytest tests/` runs the **deterministic** set: tests marked `slow` (builds a wheel or a venv),
`network` (talks to a live service) or `integration` (spawns real servers/CLIs) are deselected by
`addopts` — currently 45 of them — so a bare environment cannot hang the run. Opt in with
`-m slow`, `-m network`, `-m integration`, or `-m ""` for everything. An unreliable default teaches
people to ignore the suite; keep new environment-heavy tests behind a marker.

| Gate | What it refuses |
|------|-----------------|
| F02 `TestVersionGate` | pyproject version drift |
| F03 `TestChangelogGate` | a tagged version with no changelog entry (live *or* archive) |
| F04 `TestChangelogWindowGate` | an over-budget changelog window; rotation losing an entry |
| F05 `TestInstallPathGate` | state resolved inside an installed package |
| F06 `NoAdHocStatePathGate` | new `Path(__file__).parent.parent` state paths |
| F07 `TestSanitizationSurface` | sensitive values / internal layout in tracked files |
| F08 `StateHermeticityGate` | a test resolving state through the machine's own overrides (the suite writing the real library) |
| `scripts/doc_audit.py` | advisory only (C1-C7): paths, commands, version claims, links, coverage, en/zh drift, tracked artifacts |

Detailed gate policy: `docs/DEVELOPMENT.md`. Rationale for the split (enforced vs advisory):
a judgement call dressed as a gate gets routed around; a class a check cannot see is worse than
no check.

## Developer Conventions

### PEP8 Internationalization Standards

All Python files MUST be 100% English-only:
- **Comments** — English only (docstrings, inline comments, block comments)
- **Strings** — English only (print, log, error messages, CLI output)
- **Variable/function/class names** — English only (PEP8 naming)
- **No Chinese characters, emoji, or box-drawing characters** in .py/.yaml/.sh/.md files

Why: `conda` environment has `LC_ALL=C` which causes `UnicodeEncodeError` on non-ASCII output.

Every `.py` file must have header:
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
```

Exceptions (Chinese allowed):
| Location | What | Reason |
|----------|------|--------|
| `docs/cn/` | Chinese documentation | Intended for Chinese readers |
| `.hermes/` | Hermes agent plans | Internal tooling, not user-facing |
| `README.md` | `简体中文` navigation link only | One-line label |
| `AGENTS.md` | `中文文档` directory reference only | One-line comment |
| `docs/CHANGELOG.md` | Changelog entries | English only (PEP8 compliance) |
| `docs/CHANGELOG-archive.md` | Changelog entries rotated out of the live window | English only; written by `scripts/changelog_rotate.py`, never by hand |

### Chinese Documentation Convention

- Chinese docs live in `docs/cn/*.zh-CN.md`
- Must be **line-to-line translations** of English originals (same line count)
- This enables: diff tracking, side-by-side editing, automated sync checks
- Update English first, then mirror edits to Chinese version

### PyPI Package Release Checklist

```bash
# 0. Version rule — PyPI accepts only 0.x.0 with an ODD x (0.19.0, 0.21.0, ...); everything
#    else stays on forgejo. A public release uses these same numbers (rule 10).
# 1. Direct-url / git+ deps are rejected by PyPI — strip them in a dirty tree, build, upload,
#    then restore with `git checkout pyproject.toml` (see the pypi-publish skill, §3 scenario A).
grep -n '@ https\?' pyproject.toml

# 2. Gates + tests — the default pytest run IS the deterministic gate (slower classes are opt-in)
python -m pytest tests/                                                        # incl. tests/test_invariants.py
.venv/bin/hfpclawer store invariants --strict                                  # data gate (ratchet)
#   The store is an artifact: 25 foreign DOIs, 14 impossible years and 18 duplicate records once
#   shipped through green code gates (docs/AUDIT_CRITIQUE.md). This gate runs offline over the live
#   store; the baseline lives beside the DB and may only shrink. Re-record deliberately:
#   `store invariants --update-baseline` (and say why in the commit message).
python -m pytest tests/
python3 scripts/doc_audit.py                       # advisory (C1-C7)

# 2b. Dependencies — audit the RESOLVED set, not a hand-written list
uvx pip-audit -r requirements/core.lock.txt
uvx pip-audit -r requirements/dev.lock.txt         # only en-core-web-sm is skipped (direct URL)

# 3. Bump + tag on the development line (the changelog gates run inside release.sh)
bash scripts/release.sh 0.21.0
python3 scripts/changelog_rotate.py && python3 scripts/changelog_guard.py 0.21.0

# 4. Build + upload. Python's socket hangs on AAAA here, so force IPv4.
rm -rf dist build *.egg-info && python -m build
python /tmp/twine_v4.py upload --repository testpypi dist/*     # verify first
python /tmp/twine_v4.py upload dist/*

# 5. Verify on the index, not by the progress bar
curl -s -o /dev/null -w "%{http_code}\n" https://pypi.org/pypi/hfpclawer/0.21.0/json   # 200

# 6. Mirror the same version to the public repository (rule 10)
python3 scripts/recut-public.py --version 0.21.0 --push
```

> **Dependency advisories: read them against the right target.** Both generated locks audit
> clean; what a scanner reports against this repository comes from *stale hand-copied* requirement
> files (deleted 2026-09-17 — one was a freeze of the v0.1.3 environment) and from an *old local
> virtualenv* whose installed versions lag the declared ranges (`pyjwt`, `scrapy`, `setuptools`,
> `soupsieve`, `twisted` in one such env). Re-install the dev group before believing a local audit,
> and never re-introduce hand-maintained copies of the dependency list — regenerate the locks with
> `uv pip compile pyproject.toml [-–extra dev] -o requirements/<name>.lock.txt`.

> **A domestic mirror (uv/pip config) lags a fresh upload by hours.** `uv pip install pkg==X` then
> reports "no version … unsatisfiable" while PyPI already serves it — verify against
> `--index-url https://pypi.org/simple/` before believing a failure. Equally: `github.com` HTTPS is
> unreachable from this host, so check refs with `git ls-remote` (SSH) and the index with its JSON
> API, never with curl against the website.


## Pitfalls

### Config Cache Is Global (from expflow practice)

`_config_cache` in `config.py` is a module-level global, shared across all imports.
Tests must reset cache between runs:

```python
@pytest.fixture(autouse=True)
def reset_config():
    from hfpapers import config
    config._config_cache.clear()
    yield
```

### Circular Import in paper_store.py

`CrossrefClient.cross_verify()` in `paper_store.py` imports `HFPapersCrawler._title_similarity`:

```python
from hfpapers.evolved import HFPapersCrawler  # Inside function to avoid circular
```

Do NOT move this line to the module top level.

### Temp Directory Isolation

Test fixture `test_env` already chdir's to a temp directory. Do NOT hardcode `~/.hermes/` or other system paths.

### Test state is hermetic — machine overrides must not reach a test (2026-09-17)

`test_env` (`tests/conftest.py`) chdir's to a temp directory **and** points `HFPAPERS_DATA_DIR` at
`<tmp>/data`, clearing the `HFPCLAWER_*` roots first. Before that, a machine exporting
`HFPAPERS_DATA_DIR` (or carrying a real `config.local.yaml`) silently inverted the suite: the
fixtures resolved at the *real* store, so a bare `pytest` wrote a test row into a 3976-paper
library, and two path-invariant tests (`test_paths`, `test_pool`) went red for reasons unrelated to
the code under test. Rules that follow:

- A test must not depend on machine state. When a test needs an override, set or clear it inside
  the test with `monkeypatch` — that lands *after* the fixture and wins. F08
  (`tests/test_isolation.py`) enforces both directions mechanically.
- Do **not** set `HFPCLAWER_STATE_DIR` inside a checkout: `test_checkout_mode_uses_the_repository`
  asserts `state_root() == checkout_root()` (a checkout keeps state in the repository), so pointing
  state elsewhere reddens the gate. Real per-machine values belong in the gitignored
  `config.local.yaml` (rule 4) or in the DB-only `HFPAPERS_DATA_DIR`.
- `pytest tests/` must be equally green with and without the machine's env exported — that
  equivalence is the property F08 protects.

### Scrapy vs CLI Conflict

Scrapy's `pipelines.py` calls `ensure_paper()` directly. If the spider doesn't set `sf_id`, `StorePipeline` will skip. Check `pipelines.py` lines 38-69.

### ✅ 已核实不成立: upsert_paper() "从不 commit → 静默丢数据" (2026-08-08 复核)

> **结论**: 该坑描述 (2026-07-31 记录) 是**误诊**, 实际不存在。
> 2026-08-08 实证复核 (Python 3.11.13):

**实证证据**:
1. `upsert_paper()` 用 `with self._conn() as conn:` — Python 3.5+ 的 `with conn:`
   语义是 **正常退出自动 commit、异常回滚** (非旧版 3.4- 的"不提交")。
   ```python
   # 隔离测试 (temp db):
   sf_id = store.upsert_paper(PaperRecord(title='X', relevance=80))
   # 独立 sqlite3.connect 读取 → ✅ 数据落库
   ```
2. 生产库 587 篇全部经此代码路径写入成功 (含 377 条 cron 行) — 无数据丢失。
3. Python 文档: `Connection` 的 `__exit__` 在无异常时提交事务。

**当时真实根因 (推测)**: 2026-07-31 遇到的"数据查不到"更可能是
**嵌套库陷阱** (CWD 相对路径 → `data/data/papers.db` 空库), 已于 **v0.15.1**
修复 (`_db_path()` 相对路径对包根解析, 见下方 Pitfall)。症状相似 (写入后查不到),
但根因完全不同。

**不要做的事**: 无需给 `_conn()` 加 `isolation_level=None` 或显式 commit —
那是针对不存在的 bug 的过度工程, 且会破坏事务语义。

**遇到"数据写入后查不到"时的排查顺序**:
1. `PRAGMA database_list` — 确认连接的 DB 路径 (是否嵌套库)
2. `cd` 到项目根再运行
3. 检查 `HFPAPERS_DATA_DIR` 环境变量是否指向意外路径

### PwC API Deprecated

PapersWithCode API has been redirected to HuggingFace API. `PwcApiSource` in `sources.py` may return empty results.

### PwC API Deprecated

PapersWithCode API has been redirected to HuggingFace API. `PwcApiSource` in `sources.py` may return empty results.

### Hardware Auto-Adaptation

```python
probe = HardwareProbe()
if probe.use_pdf_converter:   # Check if pymupdf4llm is available
    ...
if probe.use_bert:            # Check CUDA + sentence-transformers
    ...
```

## File Operations (AI Assistant)

- ❌ Don't use `cat`/`grep`/`sed`/`ls` — use `read_file`/`search_files`/`patch`
- ✅ Use `write_file` for creating files, `terminal` for running commands
- ✅ Use `search_files(target="files")` instead of `ls`
- ✅ Use `search_files(pattern="content")` instead of `grep`

## Exception Handling Style: Graceful Degradation (from expflow practice)

All Python code MUST follow "never crash, always degrade" (永不休机，优雅降级):

**Rule 1: Every SDK call gets a try/except guard.**
```python
# ✅ Correct — return empty on failure
try:
    results = cr.title_to_doi(title)
except Exception:
    return None
```

**Rule 2: Non-critical operations are silent on failure.**
```python
try:
    store.add_identifier(sf_id, "doi", doi, source="crossref")
except Exception:
    pass  # Non-critical — identifier write shouldn't fail the sync
```

**Rule 3: Critical errors return a dict with "error" key.**
```python
except Exception as e:
    return {"error": str(e)}
```

**Rule 4: CLI entry point wraps everything in KeyboardInterrupt + Exception.**
```python
def main() -> None:
    try:
        app()  # Typer CLI
    except KeyboardInterrupt:
        print("Aborted.")
        sys.exit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
```

**Rule 5: MCP entry point also handles BrokenPipeError (parent disconnect).**
```python
def main() -> None:
    try:
        start_mcp()
    except KeyboardInterrupt:
        print("MCP server stopped.", file=sys.stderr)
        sys.exit(130)
    except BrokenPipeError:
        sys.exit(0)  # Parent closed stdin/stdout — normal shutdown
```

**Rule 6: Never use bare `except:`. Always specify `except Exception:` or narrower.**
- `except Exception:` catches all recoverable errors
- `except (ValueError, TypeError):` for data conversion
- `except KeyboardInterrupt:` is caught **only at the top-level entry point**

## Git Conventions

```bash
git add <files>
git commit -m "<type>: <description>"
git tag -a v0.x.y -F <notes>   # annotated: dev-line tags carry release notes
```

`.gitignore` covers: `*.db`, `data/`, `pdfs/`, `mds/`, `logs/`, `__pycache__/`, `*.egg-info/`,
`venv/`, `.ruff_cache/`, `.hermes/` (internal plans), `.codegraph/`, `sources/` (arXiv source
bundles), and the sensitive-config set: `config.local.yaml`, `.hfpclawer/`, `*_profile.yaml`,
`scripts/researcher-audit/people.yaml`

## Versioning

**Current version: read `pyproject.toml`** — the single source. (Development line `main`; the
public line is versioned on its own sequence — see `scripts/publish-public.sh`. A hand-written
version here would drift by one release every time, which is how this line read `0.3.0` once.)
- Semantic versioning with 0.x.y — x=feature iteration, y=fix/minor
- Don't bump to 1.0.0 before official release
- **`pyproject.toml` is the single source of truth** (PEP 621). `hfpapers/__init__.py` reads it and
  falls back to `importlib.metadata` only for an installed wheel — never hand-edit `__version__`
- Release through `bash scripts/release.sh <version>`: it bumps the version, commits, and refuses to
  tag a changelog that is missing the entry, over its byte budget, or has lost an entry
- Tag annotated, then push the **tag before the branch**:
  `git tag -a v0.x.y -F <notes> && git push forgejo v0.x.y && git push forgejo main`

## Naming Convention

### claw ≠ crawl (Two distinct words, not a typo)

| Word | Pronunciation | Meaning | Context |
|------|--------------|---------|---------|
| **claw** | /klɔː/ | n. sharp grasping appendage; v. to seize with claws | Animal claws, mechanical claws, raptor grasping |
| **crawl** | /krɔːl/ | v. to move slowly on hands and knees | Web crawler (spider/crawler) |

### Package name philosophy

```
hfpclawer = HF (HuggingFace Papers) + claw + er
         = "A sharp tool that claws HF papers with precision"
         ≠ crawler (web crawler)
```

- **claw** conveys precision and aggression vs **crawl** (slow, methodical)
- `clawler` = `claw` + `-er` (agent suffix)
- Complements **OpenClaw** ecosystem

### Role differentiation

| Name | Type | Semantics | Modification |
|------|------|-----------|-------------|
| `hfpclawer` | PyPI package, CLI command | claw (sharp grasper) | ✅ Correct, keep |
| `hfpapers-clawler` | GitLab repo name | claw (sharp grasper) | ✅ Correct, keep |
| `hfpclawer[arxiv]` | Optional dep | Includes Kaggle full metadata download | ✅ Recommended |
| `HFPapersCrawler` | Python class (evolved.py) | crawl (web crawl engine) | ✅ Accurate, keep |
| `HFPCrawler/1.0` | HTTP User-Agent | crawl (crawler identifier) | ✅ HTTP semantics, keep |

**Key distinction**: Package/repo name `clawler` is NOT a typo — it has a completely different etymology from the `HFPapersCrawler` class.

## Skills (Hermes Agent Skills)

The repo ships three Hermes Agent skills under `skills/`:

| Skill | File | What it automates |
|-------|------|-------------------|
| `hfpclawer-paper-search` | `skills/hfpclawer-paper-search/SKILL.md` | Daily paper discovery → download → convert → wiki sync |
| `hfpclawer-citation-audit` | `skills/hfpclawer-citation-audit/SKILL.md` | Citation verification (local → S2 → OpenAlex) |
| `hfpclawer-academic-integrity` | `skills/hfpclawer-academic-integrity/SKILL.md` | Paper draft integrity audit: extract citations → L1→L2→L3→L4 cascade → flag FABRICATED → structured report |
| `hfpclawer-formula-verify` | `skills/hfpclawer-formula-verify/SKILL.md` | LaTeX formula cross-validation: L1a syntax check → L1b SymPy↔Wolfram → L2 dimensional analysis → report |

These skills are written for **fresh Hermes Agent users** who have just
`pip install hfpclawer` and want to use the tool through natural-language
conversations. They assume zero prior knowledge of the codebase.

Install with:
```bash
hermes skills install https://raw.githubusercontent.com/diamond2nv/hfpapers-crawler/main/skills/<skill-name>/SKILL.md
```

## Internal Development

Cross-repository dependencies (expflow coupling), CodeGraph integration, and machine-specific config (WSL IPs, GPU/CPU tables) are documented in `.hermes/internal-guide.md`.
