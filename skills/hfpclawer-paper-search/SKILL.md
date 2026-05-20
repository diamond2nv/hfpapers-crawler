---
name: hfpclawer-paper-search
description: >
  Discover, download, and organize academic papers from arXiv, HuggingFace Papers,
  and OpenReview. Multi-source search → dedup → PDF download → Markdown conversion →
  optional wiki sync. Designed for researchers who want to monitor new papers daily.
category: research
author: Li Shen
version: 1.0.0
metadata:
  hermes:
    tags: [paper, search, pdf, download, research, arxiv, monitoring]
    related_skills: [hfpclawer-citation-audit]
---

# hfpclawer Paper Search & Download

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

Or run the full pipeline at once:
```bash
hfpclawer full --max-pages 3 --to-wiki
```

## Prerequisites

```bash
pip install hfpclawer>=0.5.0
hfpclawer init                      # Creates config.yaml in current directory
```

Edit `config.yaml` with your search interests (see Configuration section below).

## Quick Start

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
