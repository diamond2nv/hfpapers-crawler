# hfpapers-clawler System Architecture

> Naming Philosophy: **claw** (sharp claw) ≠ **crawl** (creep/crawl).
> Package name `hfpclawer` = HF Papers + claw + er, not crawler — faster and more precise than a web crawler.
> Meanwhile the class name `HFPapersCrawler` is the actual Scrapy crawl engine, true to its name.

## Project Overview

HF Papers multi-source paper crawler + SQLite storage engine + Crossref cross-verification + Scrapy anti-crawl + MCP remote invocation.
Focused on automated collection of academic papers in PDE/neural operator/physics-informed constraint domains, with LLM-augmented classification and arXiv ID verification.

## Architecture Layers

```
┌──────────────────────────────────────────────────────┐
│                    CLI (Typer)                        │
│   hfpclawer search | download | convert | full | ...   │
└──────────────────────┬──────────────────────────────-┘
                       │
┌──────────────────────▼──────────────────────────────-┐
│                   MCP Server                          │
│   hfpclawer_search | hfpclawer_download | ... (stdio)  │
└──────────────────────┬──────────────────────────────-┘
                       │
┌──────────────────────▼──────────────────────────────-┐
│                    Scrapy Layer                        │
│  multi_source_spider.py  |  hfspider.py               │
│  ├─ ArxivSearchSpider    ── arXiv API (Atom XML)      │
│  ├─ OpenReviewSpider     ── OpenReview API            │
│  ├─ HFPapersSpider       ── HuggingFace Papers page   │
│  └─ MultiSourceSpider    ── Multi-source unified      │
│                                                       │
│  Middleware chain: Random UA | Random Delay | Proxy   │
│  Pipeline chain: Store→Classify→Export→Download       │
└──────────────────────┬──────────────────────────────-┘
                       │
┌──────────────────────▼──────────────────────────────-┐
│                Paper Store (SQLite)                   │
│  ├─ papers table — Master paper record (Snowflake ID) │
│  ├─ identifiers table — Multi-identifier mapping       │
│  ├─ crossref_cache table — Crossref query cache        │
│  └─ CrossrefClient — Title→DOI → arXiv cross-verification│
└──────────────────────┬──────────────────────────────-┘
                       │
┌──────────────────────▼──────────────────────────────-┐
│               Core Engine (evolved.py)                │
│  ├─ DedupEngine — paper_store adapter                 │
│  ├─ HFPapersCrawler — HF CLI search + arXiv verify    │
│  ├─ RelevanceDetector — Keyword/phrase graded scoring │
│  ├─ PaperDownloader — PDF download + MD conversion    │
│  └─ Data dirs: data/ | pdfs/ | mds/                   │
└──────────────────────┬──────────────────────────────-┘
                       │
┌──────────────────────▼──────────────────────────────-┐
│               Multi-Source Searcher (sources.py)      │
│  ├─ HfCliSource      — HF CLI search (primary source) │
│  ├─ OpenReviewSource — OpenReview API + review data   │
│  ├─ PwcApiSource    — PapersWithCode API + code repos │
│  └─ ArxivApiSource  — arXiv API direct search (backup)│
└──────────────────────────────────────────────────────-┘
```

## Module Responsibilities

| Module | Responsibility | Entry Point |
|--------|---------------|-------------|
| `cli.py` | Typer CLI, 10+ subcommands | `hfpclawer` |
| `evolved.py` | Crawler core engine (HF CLI + arXiv verify) | `HFPapersCrawler` |
| `sources.py` | Multi-source search (HF/OpenReview/PwC/arXiv) | `get_enabled_sources()` |
| `paper_store.py` | SQLite store + Snowflake ID + Crossref | `PaperStore` / `ensure_paper()` |
| `config.py` | YAML config + .env + litellm pricing | `load_config()` / `get()` |
| `hardware.py` | Hardware probe (CPU/GPU/downgrade) | `HardwareProbe` |
| `mcp_server.py` | MCP stdio Server (7 tools) | `run_mcp_server()` |
| `items.py` | Scrapy PaperItem data model | `PaperItem` |
| `pipelines.py` | Scrapy Pipeline chain (4 stages) | `StorePipeline` / `ClassifyPipeline` / ... |
| `middlewares.py` | Scrapy anti-crawl middleware (6 layers) | `RandomUserAgentMiddleware` / ... |

## Data Flow

```
HF CLI search ──→ arXiv ID verification ──→ Keyword classify ──→ Dedup check ──→ SQLite store
                    ↓                                            ↓
              PDF download ←─── Candidate list JSON ←─── Sort by relevance ←─── paper_store
                    ↓
              pymupdf4llm → Markdown → mds/ directory
```

## Storage Design

- **SQLite** (`data/papers.db`): 3 tables — `papers` (master), `identifiers` (multi-identifier mapping), `crossref_cache` (API cache)
- **Snowflake ID**: 64-bit, 41bit timestamp + 10bit worker + 12bit sequence, thread-safe
- **JSON cache**: `data/candidates_latest.json` — legacy compatibility, fast queries

## Anti-Crawl Strategy

6-layer Scrapy middleware chain:

1. `RandomUserAgentMiddleware` — Random UA per request (18+ models/versions)
2. `RandomDelayMiddleware` — Random delay ±50%
3. `ProxyMiddleware` — Proxy rotation (disabled by default)
4. `CookiesPoolMiddleware` — Cookie pool (disabled by default)
5. `IntelligentRetryMiddleware` — Intelligent retry (429/403/5xx different strategies)
6. `RobustDownloaderMiddleware` — Connection timeout + exponential backoff

## Version History

- `v0.3.0` — Project migrated to `hfpapers-clawler`
- `v0.2.0` — Scrapy integration + anti-crawl middleware + distributed dedup
- `v0.1.0` — Initial version: HF CLI search + JSON dedup + keyword classification
