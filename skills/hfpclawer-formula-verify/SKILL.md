---
name: hfpclawer-formula-verify
description: >
  Verify LaTeX formulas via multi-layer cross-validation pipeline:
  SymPy roundtrip → Wolfram CAS comparison → dimensional consistency.
  Supports single FID and batch verification with LaTeX report generation.
category: research
tags: [formula-verification, sympy, latex, cas, wolfram]
author: HFPClawer Maintainers
version: 1.2.3
permissions: [shell, file_read, file_write, network]
metadata:
  hermes:
    homepage: https://github.com/diamond2nv/hfpapers-crawler
    pypi: https://pypi.org/project/hfpclawer/
    tags: [formula, verification, CAS, LaTeX, cross-validation, wolfram, sympy]
    related_skills: [hfpclawer-citation-audit, hfpclawer-paper-search]
---

# hfpclawer Formula Cross-Validation

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

Verify that a LaTeX formula is syntactically valid, algebraically
self-consistent, and dimensionally sound, by running it through a
multi-layer pipeline backed by SymPy and Wolfram Engine.

> **Who this is for**: Researchers, engineers, and physics modelers who
> need to check formula correctness before publishing or code implementation.

## Overview

The verification pipeline checks each formula through up to 4 layers:

```
                    ┌──────────────────────────┐
 User:              │ hfpclawer verify series   │
 "Verify H = -μ₀M·H"└──────────┬───────────────┘
                               │
             ┌─────────────────┼──────────────┐
             ▼                 ▼               ▼
      ┌──────────┐     ┌────────────┐   ┌─────────────┐
      │ L1a:     │     │ L1b: CAS   │   │ L2:         │
      │ LaTeX    │     │ SymPy ↔    │   │ Dimensional │
      │ Syntax   │     │ Wolfram    │   │ (pint)      │
      │ + SymPy  │     │ equivalence│   │ consistency │
      │ roundtrip│     │            │   │             │
      └──────────┘     └────────────┘   └─────────────┘
           ▼                  ▼                ▼
      ┌───────────────────────────────────────────┐
      │              Report (LaTeX .tex)          │
      └───────────────────────────────────────────┘
```

## When to Use

- You derived a formula and want to check its algebraic derivation
- You ported a formula from a paper to code and want roundtrip verification
- You need to ensure dimensionally consistent (e.g., left/right side units match)
- You want a reproducible LaTeX report of all verified formulas for publication

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

- **Optional**: Local Wolfram Engine for CAS cross-validation (L1b)
  - Download from https://www.wolfram.com/engine/
  - Set `WOLFRAMSCRIPT_PATH` in `.env` (default: `/usr/bin/wolframscript`)   - Without Wolfram, L1b skips with a warning; all other layers still run

Quick Start

### 1. Add a Formula to the Registry

```bash
# Register a formula with a unique FID
hfpclawer verify add fid001 "H = -\\mu_0 \\mathbf{M} \\cdot \\mathbf{H}_d"

# Register with source reference and tags
hfpclawer verify add jiles-ainik "H = \\alpha \\tilde{M}" \
  --source "Jiles-Atherton" \
  --tags "hysteresis,magnetic"
```

### 2. Run Verification (All Layers)

```bash
# Verify a single formula by FID
hfpclawer verify fid fid001

# Run all unverified formulas
hfpclawer verify run

# CAS cross-validation only (L1b)
hfpclawer verify cross fid001
```

### 3. Generate a LaTeX Report

```bash
# Generate verification report for one formula
hfpclawer verify report fid001 --output verify-fid001.tex

# Generate report for all verified formulas
hfpclawer verify report --all --output full-report.tex
```

### 4. Ad-Hoc Syntax Check

```bash
# Quick syntax + SymPy roundtrip without registration
hfpclawer verify check "E = mc^2"
# → LaTeX OK, SymPy roundtrip: m*c**2
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `hfpclawer verify list` | List all formulas in registry |
| `hfpclawer verify stats` | Registry statistics (total / verified / failed) |
| `hfpclawer verify add <fid> <latex>` | Register a new formula |
| `hfpclawer verify run` | Run all unverified through pipeline |
| `hfpclawer verify fid <fid>` | Verify one formula by FID |
| `hfpclawer verify check <latex>` | Ad-hoc: syntax check + SymPy roundtrip |
| `hfpclawer verify cross <fid>` | CAS cross-validation only |
| `hfpclawer verify report <fid>` | Generate LaTeX report |

## Layer Details

### L1a: LaTeX Syntax + SymPy Roundtrip

Parses the LaTeX expression, converts to SymPy, evaluates the
roundtrip (SymPy → LaTeX → SymPy). Flags discrepancies:

| Symptom | Likely Cause |
|---------|-------------|
| SymPy parsing error | Invalid LaTeX (missing braces, unsupported operators) |
| Roundtrip altered | LaTeX uses non-standard macros that SymPy doesn't recognise |
| AST mismatch | Ambiguous operator precedence |

### L1b: CAS Cross-Validation (SymPy ↔ Wolfram)

If WolframScript is available, evaluates the formula in both CAS systems
and compares their simplified forms. Reports:

- `EQUIVALENT` — sorted ASTs match
- `ALGEBRAICALLY_EQUIVALENT` — simplification needed
- `DIFFERENT` — real algebraic discrepancy (needs human review)

### L2: Dimensional Consistency

Uses `pint` to parse physical dimensions of each term:

```bash
# Internally checks:
#   [H] = A/m
#   [μ₀] = N/A²
#   [M] = A/m
#   [H_d] = A/m
#   [μ₀·M·H_d] = N/A² · A/m · A/m = N/m² = J/m³
#   [H] = A/m ≠ [μ₀·M·H_d] = J/m³  → flags unit mismatch
```

## Batch Workflow

```bash
# 1. Register multiple formulas
hfpclawer verify add fid01 "\\nabla \\times \\mathbf{H} = \\mathbf{J}"
hfpclawer verify add fid02 "\\nabla \\cdot \\mathbf{B} = 0"
hfpclawer verify add fid03 "\\mathbf{B} = \\mu_0 \\mathbf{H}"

# 2. Run all
hfpclawer verify run

# 3. Check results
hfpclawer verify stats

# 4. Generate full report
hfpclawer verify report --all --output maxwell-verify.tex
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

1. **LaTeX escaping**: Shell requires double backslash (`\\mu`), not single (`\mu`)
2. **Wolfram not installed**: L1b silently skips — use `--verbose` to see skip reason
3. **Complex multi-line formulas**: Use `align*` environment — the parser handles
   `&` alignment markers but not nested `\begin{align}`
4. **FID collisions**: Registry uses exact FID match for updates; run
   `hfpclawer verify list` before adding new formulas
5. **pint dimension database**: Custom units require entries in `pint`'s
   `default_en.txt`; standard SI units work out of the box

## Verification Checklist

- [ ] Single formula add + verify: `hfpclawer verify add test "E = mc^2"`
- [ ] Run pipeline: `hfpclawer verify fid test`
- [ ] Cross-validation: `hfpclawer verify cross test`
- [ ] LaTeX report: `hfpclawer verify report test`
- [ ] Non-registered FID returns helpful error
- [ ] Invalid LaTeX returns parse error (not crash)
