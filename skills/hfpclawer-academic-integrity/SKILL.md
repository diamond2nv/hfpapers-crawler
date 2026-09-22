---
name: hfpclawer-academic-integrity
description: >
  Feed a paper draft to automatically extract citations, verify each one
  against local + Semantic Scholar + OpenAlex, detect fabricated references,
  and generate a structured integrity report. Designed for researchers,
  reviewers, and literature-survey authors.
category: research
tags: [academic-integrity, citation-verification, hallucination, audit, research]
author: HFPClawer Maintainers
version: 1.2.3
permissions: [shell, file_read, file_write, network]
metadata:
  hermes:
    homepage: https://github.com/diamond2nv/hfpapers-crawler
    pypi: https://pypi.org/project/hfpclawer/
    tags: [academic-integrity, citation, verification, hallucination, research, audit]
    related_skills: [hfpclawer-paper-search, hfpclawer-citation-audit]
    requires:
      - hermes_tool: web_extract
      - mcp_server: arxiv-search (for citation_graph)
---

# hfpclawer Academic Integrity Audit

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

Take a paper draft (text, URL, or PDF) and verify every citation against
local FTS5 → Semantic Scholar → OpenAlex. Spot fabricated references,
misattributed authors, and wrong publication years.

> **Who this is for**: Researchers who need to fact-check citations in
> LLM-generated papers, peer review submissions, or their own drafts
> before submission.

## Overview

```
User: "Check this paper draft for citation integrity"
                      │
         ┌────────────┴────────────┐
         ▼                         ▼
  Extract citations           Load paper (text/URL/MEDIA pdf)
         │                         │
         └────────────┬────────────┘
                      ▼
         ┌─────────────────────────┐
         │  For each citation:     │
         │  L1: Local FTS5 (1ms)   │  ← hfpclawer audit
         │  L2: Semantic Scholar   │  ← hfpclawer citation_audit_s2
         │  L3: OpenAlex           │  ← hfpclawer citation_audit_oa
         │  L4: Citation Graph     │  ← MCP arxiv-search citation_graph
         └─────────────────────────┘
                      │
                      ▼
         ┌─────────────────────────┐
         │  Integrity Report       │
         │  [OK]  VERIFIED   12    │
         │  [?]  SUSPECTED   2     │
         │  [NF] NOT_FOUND   0     │
         │  [ERR] ERROR      1     │
         │  ⚠ FABRICATED     1    │  ← title+author mismatch => hallucination
         └─────────────────────────┘
```

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

**Optional but recommended**:
- Set `S2_API_KEY` env var (10x faster S2 lookups)
- Set `OPENALEX_POLITE_EMAIL` env var (10x faster OpenAlex)
- Enable **arxiv-search MCP server** in Hermes Agent config for `citation_graph`:
  ```yaml
  # ~/.hermes/config.yaml
  mcp:
    servers:
      arxiv-search:
        command: "uvx"
        args: ["arxiv-mcp-server"]  # pin a version (e.g. ==1.2.3) — unpinned launch = rug-pull risk
  ```

Quick Start

### 1. Verify a Draft Paper (most common)

Paste the paper text (including its references section) and ask:

```
> Run academic integrity audit on this draft.

[paste paper text with references]

# Output:
# ┌─────────────────────────────────┐
# │ Academic Integrity Audit Report │
# ├─────────────────────────────────┤
# │ [OK] VERIFIED  "Fourier Neural Operator" (Li, 2020)        │
# │ [OK] VERIFIED  "Physics-Informed Neural Networks" (2019)   │
# │ [?]  SUSPECTED "Deep Learning for PDEs"                    │  ← no author/date
# │ [NF] NOT_FOUND  "Novel Superconductor at 300K" (Smith 2025)│  ← possible hallucination
# │ [NF] NOT_FOUND  "Quantum PDE Solver" (Chen 2024)           │  ← possible hallucination
# └─────────────────────────────────┘
```

### 2. Audit a Paper from a URL (arXiv / blog / preprint)

```
> Check this paper for citation integrity:
> https://arxiv.org/abs/2010.08895
```

The skill will:
1. **web_extract** the paper text
2. Parse the references section
3. Run each citation through L1→L2→L3→L4
4. Return a formatted integrity report

### 3. Audit a Local PDF or Markdown File

Provide the file via Hermes Agent:

```
> Read and audit citations in MEDIA:/path/to/paper.pdf
```

The skill reads the text, extracts citations, and reports.

## How It Works

### Citation Extraction

The extractor finds these patterns:
- `"Title" (Author, Year)` — author-year-title format
- `Author (Year) "Title"` — title-quoted format
- `arXiv:XXXX.XXXXX` — arxiv IDs
- `[1] Author. "Title". Journal. Year.` — numbered bibliography (basic)

### Verification Cascade

| Level | Source | Speed | What It Confirms |
|-------|--------|-------|-----------------|
| L1 | Local FTS5 (arxiv_meta.db) | ~1ms | arXiv ID + title match |
| L2 | Semantic Scholar API | ~200ms | Title + authors + year |
| L3 | OpenAlex API | ~200ms | Title + authors + venue + DOI |
| L4 | Citation Graph (MCP) | ~500ms | Citing/cited-by validation |

### Status Definitions

| Status | Icon | Meaning |
|--------|------|---------|
| **VERIFIED** | ✅ | Found in ≥1 source with title similarity ≥0.70 |
| **SUSPECTED** | ⚠️ | Possible match (0.40-0.69) — may be real but uncertain |
| **NOT_FOUND** | ❌ | No match in any source — **potential hallucination** |
| **FABRICATED** | 🚨 | NOT_FOUND + no author match + unlikely title — **likely hallucination** |
| **ERROR** | 🔧 | Source unavailable (DB not found, rate limited) |

## Integrity Report Example

```
═══ Academic Integrity Audit ═══
Paper: "A Survey of Neural PDE Solvers"
Total citations scanned: 22
Time: 2026-05-20T14:30:00Z
─────────────────────────────────
✅ VERIFIED   15/22  (68%)
⚠️  SUSPECTED  4/22  (18%)
❌ NOT_FOUND  2/22   (9%)   ← review these
🚨 FABRICATED 1/22   (5%)   ← "Quantum Fourier Neural Net" (Li 2025)
🔧 ERROR      0/22   (0%)
─────────────────────────────────
Verification breakdown by source:
  L1 Local FTS5:   11 verified
  L2 Semantic Scholar: +6 verified (cascaded)
  L3 OpenAlex:      +2 verified (cascaded)
─────────────────────────────────
FABRICATED citations:
  🚨 "Quantum Fourier Neural Net" (Li 2025)
     No arXiv match, no S2 match, no OpenAlex match
     Title sounds AI-generated (no such paper exists)
─────────────────────────────────
Recommendations:
  - Remove 1 fabricated citation
  - Check 4 suspected citations manually (2 may be preprints w/o arXiv ID)
  - Add DOI/arXiv IDs to 3 citations for future verifiability
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

1. **arXiv-only papers** may not appear in S2 or OpenAlex for 1-2 weeks after posting.
   If a very recent paper shows NOT_FOUND, try L4 (citation graph) or check manually.

2. **Title substring matching** can produce false VERIFIED for short titles.
   e.g. "Neural Operator" → matches "Fourier Neural Operator" (accurate)
   but "Deep Learning" → too generic, will NOT_FOUND or false-match.

3. **S2 rate limits** without API key: ~1 req/s, ~100 req/day. Set `S2_API_KEY`.

4. **Local FTS5 requires arxiv-metadata-service** clone.
   Without it, the cascade starts at L2 (slower but works).

5. **Citation extractor is regex-based**, not ML-based. Some citation styles
   (especially Chicago notes-bibliography) may not be parsed correctly.
   For best results, provide the references section in plain author-title-year format.

## Verification Checklist

- [ ] Text draft: citations properly extracted and verified
- [ ] URL draft: paper fetched, references parsed
- [ ] MEDIA PDF: text extracted, citations checked
- [ ] FABRICATED citations flagged correctly
- [ ] Report includes actionable recommendations
