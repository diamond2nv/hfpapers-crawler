---
name: hfpclawer-paper-search
description: >
  Discover, download, and organize academic papers from arXiv, HuggingFace Papers,
  and OpenReview. Multi-source search → dedup → PDF download → Markdown conversion →
  optional wiki sync. Designed for researchers who want to monitor new papers daily.
category: research
author: HFPClawer Maintainers
version: 1.2.2
permissions: [shell, file_read, file_write, network]
metadata:
  hermes:
    homepage: https://github.com/diamond2nv/hfpapers-crawler
    pypi: https://pypi.org/project/hfpclawer/
    tags: [paper, search, pdf, download, research, arxiv, monitoring]
    related_skills: [hfpclawer-citation-audit]
tags: [paper, search, pdf, download, research, arxiv, monitoring]
---

# hfpclawer Paper Search & Download

> **Part of the Exo suite** — literature (`hfpclawer`) → experiments (`expflow-pde`) → proofs
> (`omega-architect`). Three independent CLIs that meet through **files and CLI calls**, never imports.
> Entry skill: `exo-suite-linkage` (wiring, cost tiers **low → medium → high**, degradation ladder).
> Install: `uv tool install hfpclawer` · `uv tool install expflow-pde` ·
> `uv tool install "omega-architect @ git+https://github.com/diamond2nv/omega-architect@v0.2.3"`

> 🔒 **Sanitization**: This skill ships in the public repo. Never embed private
> LAN IPs, real person names, or machine codenames in examples — use
> `<placeholder>` / `Jane Doe` / `dev@example.com`. Real values live in the
> repo's gitignored `.hermes/internal-guide.md`. See repo AGENTS.md
> "Public-Release Sanitization".

A multi-source academic paper pipe: search across arXiv / HuggingFace Papers /
OpenReview / PapersWithCode, deduplicate by title, download PDFs, convert to
Markdown, and optionally sync to a wiki.

> **Who this is for**: Researchers who want a daily "new papers on my topic"
> feed without manually checking multiple websites.

## Overview

Typical workflow in one command:

```
hfpclawer search           # Discover new papers across sources
   └── ranked by relevance to your keywords
hfpclawer download         # Download PDFs for matched papers  
   └── 8 concurrent streams
hfpclawer convert --to-wiki # PDF → readable Markdown + wiki sync
```

### Direct fetch of a known arXiv ID (v0.16.11+)

`hfpclawer fetch <arxiv_id>` downloads one paper by ID with a built-in
network escape ladder — **TCP quick-probe → QUIC/HTTP-3 → browser-hint**.
Use it whenever arXiv TCP/443 is RST-reset (common on CN networks); QUIC
over UDP/443 survives the reset and is the primary escape channel.

```bash
hfpclawer fetch 2609.02737                    # PDF, auto transport
hfpclawer fetch 2608.06013 -k source -t quic  # TeX bundle, force QUIC
```

Robustness built in: bounded-memory streaming (512KB flush to `.part`),
**resume on interruption** (fresh `.part` continues via `Range`; >24h stale
`.part` reclaimed), and a **sha256 integrity anchor** printed on every
completed fetch and appended to `data/download_audit.jsonl`.

**Channel-verification trick**: fetch the same arXiv ID twice — once from
the official arXiv endpoint and once from a mirror (e.g. AlphaXiv; its real
PDFs live at `pdfs.assets.alphaxiv.org`) — and compare sha256. Byte-identical
hashes verify the QUIC channel end-to-end (cross-channel MITM detection).

Or run the full pipeline at once:
```bash
hfpclawer full --max-pages 3 --to-wiki
```

## Multi-Source Registry (v0.18+)

Beyond the default HF/arXiv path, three biomedical adapters are registered — `europepmc`,
`biorxiv`, `medrxiv`. They run only when enabled:

```yaml
search:
  enabled: [hf_cli, arxiv_api, europepmc, biorxiv, medrxiv]
```

```bash
hfpclawer source-list                               # which adapters exist
hfpclawer source-search europepmc "CRISPR screen"   # query one adapter directly
```

- **Registration is not enablement** — an adapter in the registry does nothing until its key is in
  `search.enabled`, so adding one cannot change existing behaviour.
- Keep personal query lists and real names in the gitignored `config.local.yaml`;
  `search.biomed_queries: []` in the tracked file is the declared placeholder slot.
- Europe PMC returns **no abstract** unless `resultType=core` is set (the adapter sets it);
  bioRxiv/medRxiv expose a date-range API only, so keyword filtering happens at ingest.
- Transient failures retry through `anti_crawl.max_retries` / `retry_http_codes` / `retry_delay_base`.

## Prerequisites

**Python ≥ 3.10.** Pick the install that matches how you work — **uv is recommended**, because the CLI then lives in its own environment (no conflicts with your project's dependencies):

```bash
# 1) Recommended — uv tool: isolated CLI install, `hfpclawer` on your PATH
uv tool install hfpclawer
hfpclawer init                    # writes config.yaml

# 2) Try it without installing anything (ephemeral, one-off runs)
# pin the version — `uvx`/`uv tool run` reuse an installed tool env (may run an older
# release), and an unpinned launch is a supply-chain (rug-pull) risk
uvx "hfpclawer==0.19.0" --help

# 3) Inside an existing project / venv (uv-managed)
uv pip install hfpclawer

# 4) No uv yet — pip and pipx both work
pip install hfpclawer             # or: python -m pip install hfpclawer
pipx install hfpclawer            # CLI-style install, functionally like `uv tool`
```

**Optional extras** — the core install stays deliberately small:

| Extra | Adds | Install |
|:--|:--|:--|
| `zotero` | `pyzotero` — the Zotero read / write / ingest paths | `uv tool install "hfpclawer[zotero]"` |
| `nlp` | spaCy pipeline for entity enrichment | `uv tool install "hfpclawer[nlp]"` |
| `graph` | networkx + geopy for the citation graph | `uv tool install "hfpclawer[graph]"` |
| `llm` | litellm for opt-in LLM helpers (`sniff`) | `uv tool install "hfpclawer[llm]"` |

> ⚠️ **`nlp` extra + PyPI** (checked against the published 0.19.0 metadata): PyPI strips the direct-URL spaCy model, so that extra installs `spacy` only — fetch the model yourself with `python -m spacy download en_core_web_sm`. The loader falls back `configured → en_core_web_md → en_core_web_sm` and logs one actionable hint when none is present: entity enrichment degrades, nothing else breaks.

**Where to find it**: repo <https://github.com/diamond2nv/hfpapers-crawler> · PyPI <https://pypi.org/project/hfpclawer/> · registry: `clawhub inspect <slug>`

Edit `config.yaml` with your search interests (see Configuration section below).

Quick Start

### 1. First-time Setup

```bash
# Create default config
hfpclawer init

# Edit the config to match your research interests
vim config.yaml
# → Change: search.queries, keywords.include_high, keywords.exclude
```

### 2. One-Shot Full Pipeline (daily use)

```bash
# Discover → Download → Convert → Wiki sync in one command
hfpclawer full

# Limit pages for a quick check
hfpclawer full --max-pages 3 --to-wiki
```

### 3. Step-by-Step (for debugging)

```bash
# Step 1: Search across all sources
hfpclawer search --max-pages 5

# Step 2: Download PDFs for matched papers
hfpclawer download

# Step 3: Convert PDFs to Markdown
hfpclawer convert

# Step 4: Sync to wiki directory
hfpclawer convert --to-wiki
```

### 4. Monitor New Papers Regularly

```bash
# Check what papers have been downloaded
hfpclawer list

# Show paper store statistics
hfpclawer store stats

# Start the real-time download monitor
hfpclawer monitor start
```

## Configuration

The config file `config.yaml` controls what papers are searched and downloaded:

```yaml
search:
  max_per_dim: 50           # Papers per search query per source
  queries:
    - query: "neural operator"
      category: neural-operator
    - query: "physics-informed"
      category: physics-informed
    - query: "PDE solver deep learning"
      category: pde-solver

keywords:
  include_high:              # Papers must match these (OR)
    - "neural operator"
    - "pde"
    - "deep learning"
  include_low:               # Optional bonus keywords
    - "fourier"
    - "self-attention"
  exclude:                   # Exclude these topics
    - "quantum"
    - "llm"

classification:
  threshold_pass: 30         # Relevance score threshold (0-100)
  title_similarity_min: 0.40 # Dedup threshold

paths:
  data_dir: "data"           # SQLite DB location
  pdf_dir: "pdfs"            # Downloaded PDFs
  md_dir: "mds"              # Converted Markdown files
```

## Available Commands

| Command | Purpose | Common Flags |
|---------|---------|-------------|
| `hfpclawer search` | Discover new papers | `--max-pages`, `--dry-run` |
| `hfpclawer download` | Download PDFs | (runs from search results) |
| `hfpclawer convert` | Convert PDF → MD | `--to-wiki` syncs to `raw/papers/` |
| `hfpclawer full` | All-in-one pipeline | `--max-pages`, `--to-wiki` |
| `hfpclawer list` | List downloaded papers  | |
| `hfpclawer store stats` | Paper store statistics | |
| `hfpclawer store export` | Export store as JSON/CSV | `--format json` |
| `hfpclawer store verify` | Cross-verify paper metadata | `--arxiv-id` |
| `hfpclawer config` | Show current config | |
| `hfpclawer mcp` | Start MCP server | (for LLM integration) |
| `hfpclawer monitor` | Download daemon control | `start`, `stop`, `status` |
| `hfpclawer dedup` | Show dedup statistics | |

## Daily Routine Examples

### Morning — Check What's New

```bash
# Quick scan (3 pages per query, ~50 papers)
hfpclawer search --max-pages 3

# View results
hfpclawer store stats
```

### Afternoon — Download & Read

```bash
# Download all new papers
hfpclawer download

# Convert to readable markdown
hfpclawer convert

# Read the best one
cat mds/2010.08895.md | head -80
```

### Weekly — Full Pipeline

```bash
# Full sweep with wiki sync
hfpclawer full --max-pages 10 --to-wiki

# Validate references in newly added papers
hfpclawer audit verify "Key cited paper" --source openalex
```

## Data Storage

hfpclawer uses three tiers:

| Storage | Location | Content | Persistence |
|---------|----------|---------|-------------|
| SQLite | `data/papers.db` | Metadata, dedup, cross-ref | Persistent |
| PDFs | `pdfs/` | Raw paper PDFs | Download once, keep |
| Markdown | `mds/` | Converted text | Regeneratable from PDFs |

The paper store tracks:
- arXiv ID, title, authors, abstract
- Source of discovery (HF / arXiv / OpenReview)
- Download status, conversion status
- Wikified path (if synced)
- Cross-verification with Crossref (DOI validation)

## Search · Breadth · Recommend (搜广推, v0.18+)

Three families, each usable on its own — combined they form the discovery loop:

| Layer | Commands | What it does |
|:--|:--|:--|
| **搜 Search** | `search`, `convert-tex`, `sniff`, `fetch` | multi-source discovery (HF Papers + arXiv + OpenReview + biomedical), TeX source → Markdown **with formulas preserved**, opt-in LLM abstract triage, CN-aware single-paper transport |
| **广 Breadth** | `graph` (`expand-hub --audit`), `pool`, `dedup`, `batch` | citation-graph hub expansion **with an audit trail of what was adopted vs truncated**, positive-example pool, dedup statistics, queue-based batch download |
| **推 Recommend** | `recommend`, `profile`, `rank` | scored recommendations that show **why** (layer + query per row), interest profile, opt-in learned re-ranking |

```bash
# Recommend papers for this repo (fuses config queries + repo/user profile, keeps suspect out)
hfpclawer recommend --limit 10
hfpclawer recommend --path ~/my-project        # read the profile from another repo

# Show the profile that drives it (repo block + private user profile)
hfpclawer profile            # repo: hfpclawer: YAML block in the nearest AGENTS.md
hfpclawer profile --user     # private ~/.hfpclawer/profile.yaml

# Grow the positive-example pool, then train the learned re-ranker (local lightgbm)
hfpclawer pool sync-favorited                  # Zotero favorites → positives
hfpclawer pool ingest-verified                 # human-approved papers
hfpclawer pool export --out data/train.jsonl
hfpclawer rank train --audit data/expand-audit.jsonl --out data/rank_model.txt
```

**Why it is auditable**: every recommendation row carries its provenance (which layer, which
query, verification state). Suspect papers are gated out; verified ones are preferred.

## Zotero Integration (read · write · ingest)

Talks to **Zotero Desktop's local server on port 23119** — the local server needs no cloud
account; the `zotero` pyzotero extra is still required for these paths.
Zotero must be running.

| Direction | Commands | Endpoint |
|:--|:--|:--|
| **Read** | `zotero check`, `list`, `search`, `get`, `tags`, `children` | local API `/api/` |
| **Write** | `zotero push`, `zotero push-batch` | Connector protocol `/connector/` |
| **Ingest** | `zotero ingest` | Zotero local PDF → `paper_store` + `wiki/raw` + annotations |
| **Learn** | `pool sync-favorited` | Zotero favorites feed the recommendation pool |

```bash
hfpclawer zotero check                        # verify connectivity first
hfpclawer zotero list --limit 10 --tag hfpclawer
hfpclawer zotero search "neural operator" --limit 5
hfpclawer zotero get ABC123
hfpclawer zotero push <arxiv-id>              # paper_store → Zotero
hfpclawer zotero ingest ABC123                # Zotero PDF → store + wiki + annotations
```

Override `ZOTERO_API_URL` only if Zotero listens elsewhere. Real Zotero user ids are
**private** — keep them in gitignored config, never in tracked files.

## Hermes Agent Environment

hfpclawer is built to run inside **Hermes Agent** (and OpenCode) as a first-class tool —
the agent discovers the skill, and every command below is callable without leaving the session.

**1. Install the skill** — place this folder under `~/.hermes/skills/research/<slug>/`
(or install from ClawHub: `clawhub inspect <slug> --file SKILL.md`); Hermes loads it automatically
and `skill_view(name='<slug>')` returns this file.

**2. Register the MCP server** so the agent calls the CLI as tools:

```yaml
# ~/.hermes/config.yaml
mcp:
  servers:
    hfpclawer:
      command: "hfpclawer"
      args: ["mcp"]        # stdio mode — Hermes native MCP client
```
For OpenCode / debugging use HTTP mode: `hfpclawer mcp --mode http --port 8765`.

**3. Environment variables** — every one is optional; the pipeline runs with none set:

| Variable | Purpose |
|:--|:--|
| `HFPAPERS_DATA_DIR` | state/DB root (XDG `~/.local/share/hfpclawer` when installed; the checkout when run from source) |
| `HFPAPERS_CONFIG` / `HFPAPERS_LOCAL_CONFIG` | config file + private overlay |
| `S2_API_KEY` | Semantic Scholar — 10x faster (anonymous tier works) |
| `OPENALEX_POLITE_EMAIL` | OpenAlex polite pool — 10x faster |
| `ZOTERO_API_URL` | Zotero local API base (default `http://127.0.0.1:23119/api/`) |
| `HFPCLAWER_PEER_REPOS` / `HFPCLAWER_REPO_MAP` | address private sibling repos by tag instead of hard-coded paths |

**4. Cost profile** — the mechanical layer (search / dedup / verify / audit / Zotero) needs
**low-cost by design — not zero-cost.** The core path (search / dedup / verify / audit / Zotero)
issues no LLM call and needs no API key, so the marginal cost per run is small; it is still **not
zero** — bandwidth, disk and CPU are spent, and rate-limited upstreams (arXiv / OpenAlex / Semantic
Scholar) can throttle or expect a key at volume. LLM features (`sniff`, abstract triage) are opt-in
and metered where they run; `rank` trains locally with lightgbm. Describe the cost as **low**, and
keep the LLM steps explicit — do not advertise the stack as zero-token.

**5. Keep private data private** — real author lists, ORCIDs and Zotero ids belong in
`config.local.yaml` (gitignored) or `~/.hfpclawer/profile.yaml`, never in tracked files.
The repo-side profile (the `hfpclawer:` block in a project `AGENTS.md`) is deliberately
**public-safe**: neutral academic keywords only.

## Common Pitfalls

1. **`pip install` needs to be in the right venv.** If `hfpclawer` command is not
   found, check the active Python environment.
2. **HuggingFace CLI rate limits.** Too many queries per minute will trigger 429s.
   Reduce `max_per_dim` to 10 if this happens.
3. **Scrapy spiders need `scrapy` extra installed.** If you see `ModuleNotFoundError:
   scrapy`, run `pip install hfpclawer[scrapy]`.
4. **PDF conversion needs `pymupdf4llm`.** Run `pip install hfpclawer[pdf]` if
   `hfpclawer convert` complains about missing pymupdf4llm.
5. **Wiki sync defaults to `raw/papers/`.** If you do not have a wiki directory,
   skip `--to-wiki` and read from `mds/` directly.
6. **First run creates a `config.yaml`.** Edit it before running `hfpclawer full`,
   otherwise the default queries may not match your research area.

## Verification Checklist

- [ ] `hfpclawer init` creates a valid `config.yaml`
- [ ] `hfpclawer search --dry-run` validates config without network calls
- [ ] `hfpclawer search --max-pages 3` returns real papers
- [ ] `hfpclawer download` downloads PDFs correctly
- [ ] `hfpclawer convert` produces readable Markdown
- [ ] `hfpclawer store stats` shows non-zero counts
- [ ] `hfpclawer store verify --arxiv-id 2010.08895` cross-checks via Crossref
