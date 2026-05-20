---
name: hfpclawer-citation-audit
description: >
  Verify academic paper citations using a three-tier fallback pipeline:
  local FTS5 database → Semantic Scholar API → OpenAlex API.
  Supports single citation checks and batch reference-list audits.
  No external API keys required for basic usage.
category: research
author: Li Shen
version: 1.0.0
metadata:
  hermes:
    tags: [citation, audit, verification, research, academic, paper]
    related_skills: [hfpclawer-paper-search]
---

# hfpclawer Citation Audit

Verify whether a cited academic paper actually exists, using a three-tier
pipeline that degrades gracefully when local data or remote APIs are unavailable.

> **Who this is for**: Researchers, reviewers, and literature-survey authors who
> need to check whether a citation refers to a real paper.

## Overview

The audit engine tries three sources in order, stopping at the first
confirmation:

```
                    ┌──────────────────────────┐
 User:              │  hfpclawer audit verify   │
 "Is this paper     │  "Fourier Neural Operator"│
 real?"             └─────────────┬────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼              ▼
              ┌─────────┐  ┌──────────┐  ┌──────────┐
              │ L1:     │  │ L2:      │  │ L3:      │
              │ Local   │→ │ Semantic │→ │ OpenAlex │
              │ FTS5 DB │  │ Scholar  │  │          │
              │ (1ms)   │  │ (200ms)  │  │ (200ms)  │
              └─────────┘  └──────────┘  └──────────┘
```

Each source independently reports one of four statuses:
- `VERIFIED` — the paper exists in this source
- `SUSPECTED` — possible match (similar title, but not exact)
- `NOT_FOUND` — no match found
- `ERROR` — source unavailable (no local DB / API rate-limited)

## When to Use

- A user cites a paper you cannot find — verify its existence
- You team is writing a survey / literature review — batch audit the reference list
- You downloaded an LLM-generated paper and need to fact-check its citations
- You want to know whether a paper is a known arXiv preprint or a non-existent hallucination

## Prerequisites

- `pip install hfpclawer>=0.5.0`
- No API keys needed for basic use (S2 + OpenAlex use anonymous tier)
- **Optional**: Set `S2_API_KEY` env var for 10x faster Semantic Scholar lookups
- **Optional**: Set `OPENALEX_POLITE_EMAIL` env var for 10x faster OpenAlex lookups
- **Optional**: Clone `arxiv-metadata-service` repo for L1 local FTS5 (see references/local-db-setup.md)

## Quick Start

### 1. Verify a Single Citation (most common)

```bash
# Auto mode: tries local DB first, then Semantic Scholar, then OpenAlex
hfpclawer audit verify "Fourier Neural Operator for Parametric Partial Differential Equations"

# Short title works too — includes substring fallback
hfpclawer audit verify "Fourier Neural Operator"

# Exact arXiv ID
hfpclawer audit verify --arxiv-id 2010.08895
```

### 2. Use a Specific Source

```bash
# Local FTS5 only (needs arxiv_meta.db)
hfpclawer audit verify "Attention Is All You Need" --source local

# Semantic Scholar only
hfpclawer audit verify "Attention Is All You Need" --source s2

# OpenAlex only
hfpclawer audit verify "Attention Is All You Need" --source openalex
```

### 3. Check a Reference List from File

```bash
# Save citations in a text file, one per paragraph
cat > refs.txt << 'EOF'
The FNO paper (arXiv:2010.08895) shows promising results.
PINNs were introduced by Raissi et al. (2019) "Physics-informed neural networks".
EOF

hfpclawer audit --refs refs.txt
```

## Output Format

Each result shows:
- `[OK] VERIFIED` — paper confirmed; includes title, authors, source
- `[?] SUSPECTED` — possible but uncertain; shows top matches
- `[NF] NOT_FOUND` — no evidence of this paper
- `[ERR] ERROR` — source unavailable (DB not found, rate limited)

```
[OK] VERIFIED
  Title: Fourier Neural Operator
  Authors: Zongyi Li, Nikola Kovachki, Kamyar Azizzadenesheli, ...
  Sources: openalex: VERIFIED
```

## How Statuses Are Determined

| Status | Local DB | Semantic Scholar | OpenAlex |
|--------|:--------:|:----------------:|:--------:|
| VERIFIED | FTS5 match with title similarity >= 0.70 | Title search ≥ 0.70 | Title search ≥ 0.70 |
| SUSPECTED | FTS5 match with score 0.40-0.69 | — | — |
| NOT_FOUND | No FTS5 results | No ≥0.70 match | No ≥0.70 match |
| ERROR | DB not found / corrupt | 429/5xx / network | 429/5xx / network |

**Title matching**: Title similarity uses `difflib.SequenceMatcher` on
normalized (lowercase, punctuation-stripped) titles. Short titles that are
substrings of longer titles also pass the 0.70 threshold.

## Batch Modes

### From a Text File

```bash
hfpclawer audit --refs references.txt
```

The parser detects:
- arXiv:XXXX.XXXXX identifiers
- `"Title" (Author, Year)` patterns
- `Author (Year) "Title"` patterns

### Via Python API

```python
from hfpclawer.citation_audit import check_citation

result = check_citation(
    "Fourier Neural Operator",
    authors_hint="Li",
    year_hint=2020,
    source="auto",       # or "local" / "s2" / "openalex"
)
print(result["status"])  # VERIFIED | NOT_FOUND | ERROR
print(result.get("authors", "N/A"))
print(result.get("per_source", {}))  # Per-source breakdown
```

## Common Pitfalls

1. **Short/two-word queries may fail L1** because FTS5's porter stemmer requires
   actual content words. Use at least 3-4 significant words for local DB queries.
2. **Semantic Scholar rate-limits aggressively** without API key (~1 req/s,
   ~100 req/day anonymous). Set `S2_API_KEY` for production use.
3. **OpenAlex polite pool** is free and gives 10 req/s — set
   `OPENALEX_POLITE_EMAIL` to your institution email.
4. **No L1 without arxiv-metadata-service**: The local FTS5 DB requires
   `git clone` of the separate arxiv-metadata-service repo. Without it,
   the auto chain starts at L2 (slower but still works).

## Verification Checklist

- [ ] Single citation works: `hfpclawer audit verify "Known Paper Title"`
- [ ] arXiv ID works: `hfpclawer audit verify --arxiv-id 2010.08895`
- [ ] Non-existent paper returns NOT_FOUND
- [ ] Network errors return ERROR (not crash)
- [ ] Batch mode processes multiple citations from file
- [ ] `hfpclawer audit verify --help` shows source options
