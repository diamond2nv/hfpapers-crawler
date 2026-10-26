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

## Round runner: `scripts/cron_round.py` (v0.19.14)

Ingesting a round is one command now: query the axes, diff against the store, ingest what is new,
and prove the dedup path still works. It replaced the per-round one-shot scripts, which stay in
`scripts/` as provenance and are marked superseded.

```bash
python3 scripts/cron_round.py \
    --source cron-YYYY-MM-DD-roundN \
    --axis 'all:"AI for science" AND all:agent' \
    --pick 2610.06986 \
    --dedup-regression 2610.06986v1 \
    --audit-forms --json-out /tmp/round.json
```

Exit codes: `0` ok, `1` an assertion was violated, `2` usage or environment error. A dedup probe
returning `is_new=True` fails the run on purpose — that is the check the one-shot rounds kept
discovering by hand, several rounds too late.

### What long-horizon use taught us

1. **Identity is the bare id.** `2610.06986` and `2610.06986v1` are the same paper; comparing raw
   strings lets both into the store. Normalise first: `normalize_arxiv_id()` parses, while a
   `split("v")` shortcut does not — it splits on any `v`.
2. **Never write a second arXiv client.** One round used `CERT_NONE` and disabled TLS for no
   benefit. `arxiv_lookup._http_get` already handles the `406` edge fingerprint with TLS on.
3. **`urlencode`-ing a whole `search_query` empties it.** The `+` in `A+AND+B` becomes `%2B` and
   the API reads a different query. `build_axis_url()` keeps the operators literal.
4. **`year=0` is structural, not one bad row.** `ensure_paper` takes no `year`; the runner backfills
   it from `published`. A store with most years at 0 cannot answer year-based questions at all.
5. **`--audit-forms` is the drift alarm.** It finds papers held under several id forms — how the
   `x`-titled duplicate of `2609.09203` would have surfaced before it became permanent.
6. **Commit the round script.** A one-shot left untracked breaks the evidence chain: the write-up
   cites it, and no other machine can retrieve the code that selected those papers.

### Before you trust a round

```bash
python3 scripts/cron_round.py --source smoke --pick <filed-id> --dedup-regression <filed-id> --dry-run
python3 scripts/cron_round.py --source smoke --audit-forms --dry-run | python3 -m json.tool
hfpclawer store stats          # the delta you claim must match
```

A round is trustworthy when the store delta equals the `is_new=True` count, the regression probe
reports `False` on an id already filed, and `--audit-forms` shows no new duplicated pair.
