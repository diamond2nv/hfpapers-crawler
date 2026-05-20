# hfpapers-clawler Usage Guide

## Installation

```bash
# Clone project
cd ~/Gitlab/Agentic4Sci/hfpapers-clawler

# Create virtual environment (Python >= 3.10)
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e .          # Base installation
pip install -e ".[scrapy]"  # With Scrapy (requires extra dependencies)
pip install -e ".[dev]"     # With development tools
pip install -e ".[arxiv]"   # With arXiv local search (OAI-PMH or Kaggle — see [kaggle-metadata.md](kaggle-metadata.md))

# Configuration
cp env.template .env
# Edit .env to fill in API keys

# Verify
hfpclawer --help
```

> **Note**: For first-time Kaggle metadata setup (optional, ~5.3 GB download + ~11 GB index), see [kaggle-metadata.md](kaggle-metadata.md) — covers `kaggle` CLI install, API token configuration, and storage space requirements.

## CLI Commands

`hfpclawer` provides 10+ subcommands:

### Search & Crawl

```bash
# Search for new papers (HF CLI → arXiv verification → keyword classification)
hfpclawer search                     # Default: 3 pages, threshold 30
hfpclawer search --max-pages 5       # Search more
hfpclawer search --threshold 50      # Higher relevance threshold
hfpclawer search --dry-run           # Display only, don't save

# Full pipeline: search → download → convert
hfpclawer full

# Multi-source search (config-driven)
hfpclawer crawl
```

### Storage Management

```bash
# SQLite Paper Store operations
hfpclawer store stats                # Storage statistics
hfpclawer store search --keyword "FNO"  # Search papers
hfpclawer store search               # List all papers
hfpclawer store ensure --aid 2301.11167 --title "..."  # Ensure paper exists
hfpclawer store verify --aid 2301.11167 --title "..."  # CrossRef cross-verification
hfpclawer store ids --aid 2301.11167  # Lookup paper identifiers
```

### Download & Convert

```bash
# Download candidate paper PDFs
hfpclawer download                    # Download TOP-20
hfpclawer download --limit 50         # Download more

# PDF → Markdown conversion
hfpclawer convert                     # Batch pymupdf4llm conversion

# List papers
hfpclawer list                        # List crawled papers
hfpclawer info 2301.11167             # Single paper details
```

### Other

```bash
hfpclawer dedup                       # Dedup statistics
hfpclawer config                      # View current configuration
hfpclawer mcp                         # Start MCP Server (default :8765)

# Database operations
hfpclawer paper-stats                 # paper_store statistics
hfpclawer check                       # Integrity check
hfpclawer wiki                        # Wiki integration (generate wiki pages)
```

## Configuration

### config.yaml

The project root `config.yaml` is the main configuration, divided into 8 sections:

1. **search** — Search source config, search dimensions, keywords
2. **keywords** — Keyword whitelist (high/medium/low) + blacklist
3. **anti_crawl** — Anti-crawl strategy parameters
4. **classification** — Classification thresholds
5. **hardware** — Hardware resource budget
6. **budget** — Token/cost budget
7. **wiki** — Wiki integration configuration
8. **paths** — Data/output paths

### .env

```bash
# API Keys
DEEPSEEK_API_KEY=***
HF_TOKEN=***                      # HuggingFace Token

# Proxy
HTTP_PROXY=http://127.0.0.1:7890
HTTPS_PROXY=http://127.0.0.1:7890

# Ollama local model (fallback)
OLLAMA_API_BASE=http://localhost:11434

# LiteLLM Proxy
LITELLM_PROXY=http://localhost:4000
LITELLM_API_KEY=***
```

## Scrapy Usage

```bash
# Standalone mode
scrapy crawl arxiv_search            # arXiv API search
scrapy crawl openreview              # OpenReview search
scrapy crawl hfpapers                # HF Papers page crawling
scrapy crawl multi_source            # Multi-source unified dispatch

# Distributed mode (requires Redis)
scrapy crawl multi_source -s SETTINGS_MODULE=hfpapers.settings_redis
```

## MCP Remote Invocation

MCP Server integrates with Hermes Agent / OpenCode via the stdio protocol:

```bash
# Start MCP Server
hfpclawer mcp

# Or specify port
hfpclawer mcp --port 8765 --host 0.0.0.0
```

### Available Tools

| Tool Name | Description |
|-----------|-------------|
| `hfpclawer_search` | Search for new papers |
| `hfpclawer_download` | Download PDF |
| `hfpclawer_convert` | PDF → Markdown |
| `hfpclawer_info` | Lookup paper details |
| `hfpclawer_list` | List crawled papers |
| `hfpclawer_stats` | Crawler statistics |
| `hfpclawer_full` | Full pipeline |

## Data Directory

```
hfpapers-clawler/
├── data/           # SQLite DB + JSON candidate list
│   └── papers.db  # SQLite paper_store
├── pdfs/           # Downloaded PDFs
├── mds/            # Markdown conversion results
├── logs/           # Scrapy logs
└── md_extracts/    # Fallback MD extraction directory
```
