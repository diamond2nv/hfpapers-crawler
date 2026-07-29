---
name: hfpclawer-formula-verify
description: >
  Verify LaTeX formulas via multi-layer cross-validation pipeline:
  SymPy roundtrip → Wolfram CAS comparison → dimensional consistency.
  Supports single FID and batch verification with LaTeX report generation.
category: research
author: Li Shen
version: 1.0.0
metadata:
  hermes:
    tags: [formula, verification, CAS, LaTeX, cross-validation, wolfram, sympy]
    related_skills: [hfpclawer-citation-audit, hfpclawer-paper-search]
---

# hfpclawer Formula Cross-Validation

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

- `pip install hfpclawer>=0.14.0`
- **Optional**: Local Wolfram Engine for CAS cross-validation (L1b)
  - Download from https://www.wolfram.com/engine/
  - Set `WOLFRAMSCRIPT_PATH` in `.env` (default: `/usr/bin/wolframscript`)   - Without Wolfram, L1b skips with a warning; all other layers still run

## Quick Start

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
