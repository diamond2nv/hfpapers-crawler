# hfpapers-clawler — AI Agent Development Guide

This file is for AI coding assistants (Hermes Agent, OpenCode, Claude Code, etc.)
working on this project. It describes the project structure, key patterns, pitfalls, and constraints.

## Quick Navigation

```
/Agentic4Sci/hfpapers-crawler/        ← Canonical location
└── forgejo-self-host/hfpapers-crawler → symlink → ../Agentic4Sci/hfpapers-crawler
├── hfpapers/             # Main Python package
├── hfpclawer/            # Download pipeline (OAI-PMH, Kaggle, monitor)
├── tests/                # pytest tests
├── scripts/              # Utility scripts (publish, OAI download)
├── docs/                 # English documentation
│   └── cn/               # 中文文档 (Chinese docs)
├── config.yaml           # Main config (YAML + .env override)
├── pyproject.toml        # Package config (setuptools)
├── run.sh                # One-click pipeline runner
├── AGENTS.md             # ← This file
└── .gitignore
```

## Repo Standards

| PEP | Rule | How |
|-----|------|-----|
| 621 | **Version source** | `pyproject.toml` only; `__init__.py` reads via `importlib.metadata`/`tomllib` |
| — | **Commit message version** | `v0.{x}.{y}: 描述`. 版本号**必须来自 pyproject.toml**，禁止自行编撰（如 commit msg 写 v0.13.x 但 toml 是 0.12.x）。hotfix 按最新 tag 系列递增 |
| 660 | **Editable install** | `pip install -e .` must work (has `[build-system]`) |
| 8 | **Code style** | ruff (100 chars, double quotes); 100% English in .py |
| — | **.gitignore** | Must cover: `__pycache__/ *.egg-info/ dist/ build/ .venv/ .env` |
| — | **Version mgmt** | `bash scripts/release.sh VERSION --push`; alignment=hotfix, no force tag |

> Templates and installer: `~/.hermes/skills/software-development/version-management/`

## Environment & Connectivity

Zotero local API runs on localhost:23119 (both machines). See `.hermes/internal-guide.md` for machine-specific details (WSL IPs, GPU/CPU tables).

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

### Chinese Documentation Convention

- Chinese docs live in `docs/cn/*.zh-CN.md`
- Must be **line-to-line translations** of English originals (same line count)
- This enables: diff tracking, side-by-side editing, automated sync checks
- Update English first, then mirror edits to Chinese version

### PyPI Package Release Checklist

```bash
# 0. Check for direct-url / git+ deps (PyPI rejects them)
grep -n '@ https\?' pyproject.toml
grep -n 'git+' pyproject.toml
# If found: comment out → build → upload → restore (see pypi-publish skill)

# 1. Format & lint
ruff format .
ruff check --fix .

# 2. Type check
pyright .

# 3. Test
python -m pytest tests/ -v

# 4. Build + verify
python -m build
twine check dist/*

# 5. Release (sync toml → __init__ → commit → tag → push)
bash scripts/release.sh 0.9.12 --push

# 6. Publish — always TestPyPI first, then PyPI
twine upload --repository testpypi dist/*   # Verify
twine upload dist/*                          # Production
```

> ⚠️ **publish.sh 绕行须知**: `scripts/publish.sh` 有 git status 检查，pyproject.toml 临时改动（如移除直链 dep）时会被拒绝。此时手动 `python -m build` + `twine upload --repository testpypi dist/*` 绕过。详见 `~/.hermes/skills/devops/pypi-publish/SKILL.md`。

> ⚠️ **版本管理变迁**: 旧版使用 pre-push hook + install-hooks.sh 在 push 前检查。
> 2026-07-08 重构为 `scripts/release.sh` 单入口，pre-push hook 和 install-hooks.sh 已移除。
> 所有版本发布必须走 `bash scripts/release.sh VERSION`，避免两文件脱节。
```

### Testing Before Release

- `ruff check .` must pass with **zero errors** (including tests/)
- `pytest` must pass all tests (currently 252 tests)
- `pyright` warnings for missing imports (torch, scrapy, sentence_transformers) are acceptable — these are optional dependencies
- Pre-existing warnings (unused `l` variable, None-guard noise) are non-blocking

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
git tag v3.1.0          # Semantic versioning
```

`.gitignore` covers: `*.db`, `data/`, `pdfs/`, `mds/`, `logs/`, `__pycache__/`, `*.egg-info/`, `venv/`, `.ruff_cache/`

## Versioning

**Current version: 0.3.0** (pre-release)
- Semantic versioning with 0.x.y — x=feature iteration, y=fix/minor
- Don't bump to 1.0.0 before official release
- Version defined in `hfpapers/__init__.py` `__version__`
- Sync `pyproject.toml` version field
- Tag: `git tag v0.x.y && git push --tags`

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
