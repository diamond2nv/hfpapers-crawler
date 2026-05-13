# hfpapers-clawler — AI Agent Development Guide

This file is for AI coding assistants (Hermes Agent, OpenCode, Claude Code, etc.)
working on this project. It describes the project structure, key patterns, pitfalls, and constraints.

## Quick Navigation

```
~/Gitlab/Agentic4Sci/hfpapers-clawler/
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
pyright .                   # Type check (0 errors)
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

### Chinese Documentation Convention

- Chinese docs live in `docs/cn/*.zh-CN.md`
- Must be **line-to-line translations** of English originals (same line count)
- This enables: diff tracking, side-by-side editing, automated sync checks
- Update English first, then mirror edits to Chinese version

### PyPI Package Release Checklist

Before tagging a release:

```bash
# 1. Format & lint
ruff format .
ruff check --fix .

# 2. Type check
pyright .

# 3. Test
python -m pytest tests/ -v

# 4. Verify version alignment
grep __version__ hfpapers/__init__.py  # e.g. '0.3.1'
grep ^version pyproject.toml           # Must match

# 5. Build + verify
python -m build
twine check dist/*

# 6. Tag
git tag v0.3.1
git push --tags

# 7. Publish
twine upload dist/*
```

### Testing Before Release

- `ruff check .` must pass with **zero errors** (including tests/)
- `pytest` must pass all tests (currently 91 tests)
- `pyright` warnings for missing imports (torch, scrapy, sentence_transformers) are acceptable — these are optional dependencies
- Pre-existing warnings (unused `l` variable, None-guard noise) are non-blocking

## Pitfalls

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
