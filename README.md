<p align="center">
  <a href="README.md">English</a> | <a href="docs/cn/README.zh-CN.md">简体中文</a>
</p>

# hfpapers-crawler

[![PyPI version](https://img.shields.io/pypi/v/hfpclawer)](https://pypi.org/project/hfpclawer/)
[![Python versions](https://img.shields.io/pypi/pyversions/hfpclawer)](https://pypi.org/project/hfpclawer/)
[![License](https://img.shields.io/github/license/diamond2nv/hfpapers-crawler)](https://github.com/diamond2nv/hfpapers-clawler/blob/master/LICENSE)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/diamond2nv/hfpapers-crawler)

> **Naming philosophy**: `claw` (sharp grasp) ≠ `crawl` (creep).
> `hfpclawer` = **H**ugging**F**ace **P**apers + **claw** + **er**
> = "A sharp tool that claws HF papers with precision" 🦞
>
> Not a crawler — faster, sharper, more precise. Same series: OpenClaw, Hermes Agent ecosystem.

A multi-source academic paper clawler for PDE / neural operator / physics-informed ML.
Built with SQLite paper_store, Crossref cross-validation, anti-crawl Scrapy pipelines, and MCP server.

## ✨ Features

- **Research-engineered paper discovery** — arXiv / OpenReview / Semantic Scholar multi-source clawling with relevance scoring, citation-graph analysis, and hub-guided layered expansion (`graph expand-hub`, SimClusters-inspired) for "find papers like this one" exploration.
- **Verification status machine (v0.16+)** — every paper carries an explicit, derived state: `pending → verified / stale / suspect`. Metadata conflicts (e.g. a DOI resolving to a different arXiv ID than recorded) are flagged **suspect** by symbolic 0-LLM checks and require human adjudication — no silent corruption, no LLM-judged verdicts.
- **First-party recommendation signals** — search history × text similarity + relevance scoring + verification-state gating, all computed from your local store. **No external dependency**: works fully offline, no Zotero required. Zotero (when present) is an optional enhancement adapter — only DOI/arXiv-bearing scholarly items from your library sync back as interest signals.
- **Zero-token operation ready** — deterministic change detection + cron/monitor layering keeps routine monitoring at 0 LLM cost (see Hermes Agent integration skills).

---

## Quick Install

```bash
pip install hfpclawer
```

### Dependencies

- **Core** (auto-installed): pyyaml, requests, beautifulsoup4, typer, etc.
- **LLM features** (optional): `pip install hfpclawer[llm]` — for `sniff` / `analyze` commands
- **PDF conversion** (optional): `pip install hfpclawer[pdf]`
- **Scrapy spiders** (optional): `pip install hfpclawer[scrapy]`
- **Dev** (testing): `pip install hfpclawer[dev]`
- **arXiv local search** (optional): `pip install hfpclawer[arxiv]` documents the metadata dependency only (PyPI doesn't support `git+https`). See [docs/kaggle-metadata.md](docs/kaggle-metadata.md) for manual `git clone` + OAI-PMH or Kaggle setup.
- **Citation audit** (optional): `pip install hfpclawer[audit]` declares namespace only. See [hfpclawer/citation_audit.py](hfpclawer/citation_audit.py) for manual setup.

### Local Development

```bash
git clone <your-repo>
cd hfpapers-clawler

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Verify
hfpclawer --help
```

### Configuration

First run `hfpclawer init` to generate config and env template:

```bash
hfpclawer init --quick          # Quick mode (defaults)
# or
hfpclawer init                  # Interactive wizard
cp .env.template .env           # Fill in API keys
# Edit config.yaml to customize search queries
```

Or manually create files (see [docs/USAGE.md](docs/USAGE.md) for full reference):

---

## CLI Commands

```bash
# Search for new papers
hfpclawer search                    # Default 3 pages, threshold 30
hfpclawer search --max-pages 5      # More pages
hfpclawer search --dry-run          # Show only, don't save

# Full pipeline: search → download → convert
hfpclawer full

# SQLite Paper Store operations
hfpclawer store stats               # Storage statistics
hfpclawer store search              # List all papers
hfpclawer store search --keyword "FNO"
hfpclawer store verify --aid 2301.11167

# Download & convert
hfpclawer download                  # Download top-20 PDFs
hfpclawer convert                   # PDF → Markdown

# MCP Server (for Hermes Agent / OpenCode)
hfpclawer mcp                       # Default port :8765
```

---

## Python API

```python
from hfpapers.paper_store import PaperStore, PaperRecord, ensure_paper

# Create a store
store = PaperStore(db_path="/tmp/papers.db")

# Add a paper
rec = PaperRecord(
    title="Fourier Neural Operator",
    abstract="Learning PDE solution operators with Fourier transforms",
    year=2023,
    source="my_app",
    relevance=90,
)
sf_id = store.upsert_paper(rec)
store.add_identifier(sf_id, "arxiv", "2010.08895")

# Search
papers = store.search_papers("neural operator")
for p in papers:
    print(f"[{p.relevance}] {p.title}")

# Hardware probe
from hfpapers.hardware import HardwareProbe
hw = HardwareProbe()
print(f"Hardware: {hw.summary()}")
```

---

## MCP Server

hfpapers-clawler ships with a built-in MCP server for AI agent integration:

```bash
hfpclawer mcp
```

Register in Hermes Agent `~/.hermes/config.yaml`:

```yaml
mcp:
  servers:
    hfpapers:
      command: "hfpclawer"
      args: ["mcp", "--port", "8765"]
```

Available MCP tools (4 core always active; heavy ops use CLI):

| Tool | MCP (auto) | CLI preferred |
|------|:----------:|:-------------:|
| `hfpclawer_search` | ✅ | — |
| `hfpclawer_info` | ✅ | — |
| `hfpclawer_list` | ✅ | — |
| `hfpclawer_stats` | ✅ | — |
| `hfpclawer_download` | ⚠️ available | `hfpclawer download --limit N` |
| `hfpclawer_convert` | ⚠️ available | `hfpclawer convert` |
| `hfpclawer_full` | ⚠️ available | `hfpclawer full` |

> Heavy operations (download/convert/full) are hidden from `tools/list` by default to save tokens.
> They remain callable via direct `tools/call` — or better, use the CLI for progress feedback.

---

## Architecture

```
┌─ CLI (Typer) ─┐  ┌─ MCP Server ─┐
└──────┬────────┘  └──────┬───────┘
       └────────┬──────────┘
                ▼
┌─ Scrapy Layer (Multi-source) ───────────┐
│  ArxivSearchSpider | OpenReviewSpider    │
│  HFPapersSpider | MultiSourceSpider      │
│  Middleware: UA random, delay, proxy...  │
│  Pipeline: Store→Classify→Export→DL     │
└──────────────────┬──────────────────────┘
                   ▼
┌─ Paper Store (SQLite) ──────────────────┐
│  papers (Snowflake ID) | identifiers    │
│  crossref_cache | CrossrefClient        │
└─────────────────────────────────────────┘
```

---

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v           # Run all tests
pytest tests/ --cov=hfpapers  # With coverage
```

---

## License

MIT

## Hermes Agent Skills

These skills automate common hfpclawer workflows inside **Hermes Agent** (or any
AI coding assistant that supports the Hermes skill format):

| Skill | Purpose | Install |
|-------|---------|---------|
| `hfpclawer-paper-search` | Daily paper discovery → download → wiki | `hermes skills install https://raw.githubusercontent.com/diamond2nv/hfpapers-crawler/main/skills/hfpclawer-paper-search/SKILL.md` |
| `hfpclawer-citation-audit` | Verify citations via S2 + OpenAlex | `hermes skills install https://raw.githubusercontent.com/diamond2nv/hfpapers-crawler/main/skills/hfpclawer-citation-audit/SKILL.md` |
| `hfpclawer-academic-integrity` | Paper draft integrity: extract → verify → flag FABRICATED | `hermes skills install https://raw.githubusercontent.com/diamond2nv/hfpapers-crawler/main/skills/hfpclawer-academic-integrity/SKILL.md` |
| `hfpclawer-formula-verify` | LaTeX formula cross-validation (SymPy ↔ Wolfram, dimensional) | `hermes skills install https://raw.githubusercontent.com/diamond2nv/hfpapers-crawler/main/skills/hfpclawer-formula-verify/SKILL.md` |

After installing, load with `skill_view(name='hfpclawer-paper-search')` in any
Hermes conversation.

## Acknowledgments

This project incorporates code adapted from:

- **academic-research-skills** by Cheng-I Wu
  (https://github.com/Imbad0202/academic-research-skills)
  - `hfpclawer/_text_similarity.py` — title normalization and similarity scoring
  - `hfpclawer/citation_audit_s2.py` — Semantic Scholar API client (architecture reference)
  - `hfpclawer/citation_audit_oa.py` — OpenAlex API client (architecture reference)
  Licensed under CC BY-NC 4.0 (https://creativecommons.org/licenses/by-nc/4.0/)

- **mirobody** by thetahealth
  (https://github.com/thetahealth/mirobody)
  - Design inspiration only (no code reuse): the controlled-vocabulary alignment
    spectrum (symbolic decision over learned ranking in high-error-cost domains),
    abstain-as-first-class-state, and COVERAGE_FLOOR ratchet discipline shaped the
    v0.16 metadata verification & self-assessment roadmap.
  Licensed under its own terms (https://github.com/thetahealth/mirobody)

## Links

- [Full Usage Guide](docs/USAGE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Developer Guide](docs/DEVELOPMENT.md)
- [Paper Store Reference](docs/paper_store.md)
