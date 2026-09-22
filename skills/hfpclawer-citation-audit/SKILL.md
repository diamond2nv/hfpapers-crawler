---
name: hfpclawer-citation-audit
description: >
  Verify academic paper citations using a three-tier fallback pipeline:
  local FTS5 database → Semantic Scholar API → OpenAlex API.
  Supports single citation checks and batch reference-list audits.
  No external API keys required for basic usage.
category: research
author: HFPClawer Maintainers
version: 1.2.2
permissions: [shell, file_read, file_write, network]
metadata:
  hermes:
    homepage: https://github.com/diamond2nv/hfpapers-crawler
    pypi: https://pypi.org/project/hfpclawer/
    tags: [citation, audit, verification, research, academic, paper]
    related_skills: [hfpclawer-paper-search]
tags: [citation, audit, verification, research, academic, paper]
---

# hfpclawer Citation Audit

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

- No API keys needed for basic use (S2 + OpenAlex use anonymous tier)
- **Optional**: Set `S2_API_KEY` env var for 10x faster Semantic Scholar lookups
- **Optional**: Set `OPENALEX_POLITE_EMAIL` env var for 10x faster OpenAlex lookups
- **Optional**: Clone `arxiv-metadata-service` repo for L1 local FTS5 (see references/local-db-setup.md)

Quick Start

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
