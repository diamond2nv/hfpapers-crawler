# hfpclawer Cron Automation — User Guide

## Quick Start (3 minutes)

### 1. Install

```bash
pip install hfpclawer
```

### 2. Init

```bash
# Pick one of:
hfpclawer cron init --name my-field --query "cat:cs.AI+AND+abs:neural+operator"
hfpclawer cron init --name my-field --keywords "neural operator, deep learning, PDE"
hfpclawer cron init --name my-field --from-config /path/to/existing/config.yaml
```

This creates:
- `~/.hfpclawer/config.yaml` — Edit your arXiv queries
- `~/.hfpclawer/scripts/hfpclawer-cron-fetch.sh` — For system crontab
- `~/.hfpclawer/data/paper_store.db` — Your paper database

### 3. Customize

```bash
$EDITOR ~/.hfpclawer/config.yaml
```

Add multiple domains:

```yaml
cron:
  domains:
    - name: "my-ai-field"
      query: "cat:cs.AI+AND+abs:graph+neural+network"
      category: "AI"
    - name: "physics"
      query: "cat:physics.comp-ph+AND+abs:neural+operator"
      category: "neural-operator"
  post_verify: true
```

### 4. Run

```bash
hfpclawer cron run
```

### 5. Schedule

**System crontab (0 token):**
```bash
crontab -e
59 18 * * 1  ~/.hfpclawer/scripts/hfpclawer-cron-fetch.sh --json
```

**Hermes cron (LLM-driven):**
```bash
hermes cron create \
  --schedule "0 18 * * 1" \
  --prompt "Run 'hfpclawer cron run' and summarize new papers" \
  --skills hfpclawer-cron
```

## Commands Reference

| Command | Description |
|:--------|:------------|
| `hfpclawer cron init` | Initialize ~/.hfpclawer/ config + scripts |
| `hfpclawer cron check` | Show configuration status |
| `hfpclawer cron run` | Execute fetch + import pipeline |
| `hfpclawer cron import` | Import from candidates/jsonl |
| `hfpclawer audit cron-verify` | Deferred Crossref verify + retraction check |

## DB Location (3-tier)

The paper_store.db location follows this priority:

1. **`HFPCLAWER_DATA` env var** — Override for CI/docker
2. **`~/.hfpclawer/data/paper_store.db`** — Default
3. **Custom `--data-dir`** — Written as absolute path in generated script

## Verification Pipeline

Cron imports skip Crossref verification for speed (`skip_crossref=True`). To verify later:

```bash
# Verify all unverified cron papers
hfpclawer audit cron-verify

# Check only retractions (0 Crossref calls)
hfpclawer audit cron-verify --retraction-only

# Re-verify all cron papers
hfpclawer audit cron-verify --all
```

## Using with hfpclawer paper_store

After cron imports, papers appear in paper_store with source tag `cron:<domain>`:

```bash
hfpclawer store stats              # Show all paper counts
hfpclawer store search --keyword MFL  # Search imported papers
hfpclawer cron check               # Show cron-specific stats
```
