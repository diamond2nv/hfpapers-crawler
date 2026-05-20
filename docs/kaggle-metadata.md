# Kaggle arXiv Metadata Setup

## Overview

`hfpclawer[arxiv]` provides two offline arXiv metadata search methods:
1. **OAI-PMH** (recommended): No API key, daily incremental sync, faster initial setup
2. **Kaggle JSONL** (fallback): Single ~5.3GB dump, ~11GB local SQLite FTS5 index

> ⚠️ **PyPI limitation**: `pip install hfpclawer[arxiv]` only registers the namespace — it will **NOT** auto-install `arxiv-metadata-service` (PyPI doesn't support `git+https` dependencies). Follow the manual setup steps below.

## Manual Install arxiv-metadata-service

```bash
git clone https://github.com/diamond2nv/arxiv-metadata-service.git
cd arxiv-metadata-service
pip install -e .
python arxiv_meta_cli.py --help
```

## Storage Requirements

| Source | Size | Format | Notes |
|--------|------|--------|-------|
| **Kaggle JSONL** | ~5.3 GB | Single `.jsonl` file | Full dump, weekly updated |
| **OAI-PMH SQLite + FTS5** | ~11 GB | SQLite DB with FTS5 | Daily incremental sync, faster search, no API key needed |

Choose Kaggle if you want the quickest one-shot download. Choose OAI-PMH if you want incremental updates and faster full-text search.

## Kaggle Setup Steps

### 1. Install Kaggle CLI

```bash
pip install kaggle
```

### 2. Get Kaggle API Token

1. Sign in to [kaggle.com](https://www.kaggle.com)
2. Go to **Account → API → Create New API Token**
3. Download `kaggle.json`

### 3. Configure Token

```bash
# Linux / macOS
mkdir -p ~/.kaggle
mv ~/Downloads/kaggle.json ~/.kaggle/
chmod 600 ~/.kaggle/kaggle.json

# Windows (PowerShell)
# mkdir $env:USERPROFILE\.kaggle
# Move kaggle.json to that directory
```

### 4. Download arXiv Dataset

```bash
# ~5.3 GB download
kaggle datasets download Cornell-University/arxiv
unzip arxiv.zip -d data/
# Result: data/arxiv_metadata.jsonl (~5.3 GB, ~3.0M papers)
```

### 5. Import to hfpclawer

```bash
# Import Kaggle JSONL → hfpapers SQLite storage
python scripts/import_arxiv_metadata.py --jsonl data/arxiv_metadata.jsonl
```

### 6. Verify

```bash
hfpclawer store stats
# Expected: ~3.0M papers imported
```

## OAI-PMH Alternative (No API Key, Daily Incremental)

If you prefer not to use Kaggle:

```bash
pip install hfpclawer[arxiv]  # installs arxiv-metadata-service
hfpclawer arxiv download --tier 1  # Starts OAI-PMH download (Tier 1: ~5M papers)
```

The OAI-PMH method downloads metadata from the arXiv OAI endpoint (free, no API key) and builds a local FTS5 index (~11 GB). It supports incremental sync (`--incremental 7`) and resume.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `kaggle: command not found` | Run `pip install kaggle` and ensure `~/.local/bin` is in PATH |
| `403 Forbidden` on Kaggle download | Check that `~/.kaggle/kaggle.json` exists with `chmod 600` |
| Not enough disk space | Kaggle JSONL: 5.3 GB download + 5.3 GB unzipped. OAI-PMH: ~11 GB final DB. Ensure at least 20 GB free |
| Slow OAI-PMH download | Expected — arXiv enforces 1 query/4s. Tier 1 (~5M papers) takes 12-24 hours. Use `resume_download()` |
