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

## arXiv Fetch Transport Layer (v0.16.11+)

**Problem**: arXiv HTTPS (TCP/443) is intermittently RST-reset on CN networks.
The fetch path is a layered escape ladder, not a single transport.

```
CLI `fetch` auto → 1. tcp quick-probe (fast when the link is open)
                 → 2. QUIC / HTTP/3 (UDP/443) — survives TCP RST; primary CN path
                 → 3. browser-hint error (tells the user to use a browser profile)
```

- **QUIC (H3) client**: aioquic, generous windows (32MB max_data/stream) —
  arXiv PDFs run 1-6MB over UDP and default aioquic windows throttle badly.
- **Bounded-memory streaming (sink)**: data flushes to `<dest>.part` every
  512KB (`_flush_body`); peak RAM = O(512KB × streams), not O(file size).
  aiofiles was evaluated and rejected — it is a thread-pool wrapper for
  blocking writes and cannot be awaited inside aioquic's sync event
  callbacks; a sync short append per flush chunk is the right tool.
- **`.part` lifecycle**: fresh `.part` resumes from its byte offset via
  `Range: bytes=N-`; one older than 24h (stale) is discarded (dead-session
  orphans never accumulate). On stream end: residual tail appended → sha256 →
  rename to destination. 416 from the server promotes a ≥5000B `.part`.
- **sha256 integrity anchor**: every completed fetch returns the file hash —
  the audit record for cross-channel MITM comparison. Verified practice:
  a QUIC direct fetch of the arXiv official copy and an AlphaXiv mirror copy
  are **byte-identical (matching sha256)** — cross-channel agreement is the
  reliability test for the QUIC channel. Note: AlphaXiv's real PDFs live on
  `pdfs.assets.alphaxiv.org` (not the main site).
- **Payload validation (v0.16.14 fix)**: with a sink, the payload head is
  flushed to disk before the transfer ends, so the in-memory residual tail is
  mid-file by construction and can never pass a magic check. Sink-path
  validation checks the **disk file head + assembled total** instead:
  size ≥ `_MIN_BYTES`, then kind magic on disk (PDF `%PDF`, source gzip
  `1f 8b`, raw-tex NUL-sample of the flushed region). Memory-tail magic only
  applies when no sink exists (payload < flush_every, all in RAM).
  Small-file and resume paths are unaffected by construction (no sink /
  `range_from > 0` take the legacy branches).

## State Semantics & Recommendation Signals (v0.16+)

**Verification state machine** — derived, single source of truth, symbolic verdicts (no LLM):

```
pending  → audit_level == 0, never judged
suspect  → suspect column != ''   (explicit abstain: audit conflict / unverifiable;
           FIRST-CLASS state ≠ "unaudited"; human must adjudicate via
           `store clear-suspect` / raising audit_level)
verified → audit_level >= 1
stale    → verified but audit_level_at older than stale_days (default 180)
```

- Conflict detection (`detect_identifier_conflicts`): DOI (via crossref_cache) resolving to a different arXiv ID than recorded → flagged, symbolically, 0-LLM.
- Migration v3 added `suspect`/`suspect_at`; migrations are idempotent try-ALTER.

**Recommendation signal layering** — first-party local first, external optional:

```
Layer 1 (always on, offline): config search.queries × text similarity + relevance
                               + verification gate (suspect never recommended,
                                 verified preferred, stale down-weighted)
Layer 2 (optional adapter):    Zotero local API — Favor/Extra sync BACK into
                               paper_store (favorited), only DOI/arXiv-bearing
                               scholarly items; absent → Layer 1 is unaffected
```

Design lineage: SKILL.state (explicit mutable state over append-only history) for the
status machine; Mirobody spectrum (symbolic over learned ranking in high-error-cost
domains) for the verdict predicates; zero-token monitor layering for cost control.

**Expansion & learned ranking (v0.16.1–v0.16.2)** — the graph-side analogue:

```
HubGuidedExpander
├─ run()                  hub truncation: expand → PageRank+degree top-k frontier
│                         (diffusion-control discipline inspired by SimClusters)
├─ community_guided_run() faithful SimClusters 2-hop: seed → Louvain community
│                         → community hub papers (topic-focused frontier);
│                         audit rows carry a `community` feature
└─ audit trail (JSONL)    every run can write per-candidate rows
                          (arxiv_id/adopted/hub_score/degree/layer[/community])
        ↓
hfpapers/rank.train()     lightgbm on that trail: adopted = positive,
                          truncated = negative; feature importance = audit
                          (optional `hfpclawer[rank]`; native model artifact)
```

Contract models (`hfpapers/contracts.py`, pydantic) exist ONLY at API/JSON
boundaries — ZoteroItem encodes the scholarly filter (DOI/arXiv identifier
judgment) for sync-back; the mechanical layer stays plain-dict with defensive
reads (repo discipline: no pydantic inside 0-token pipelines).

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
