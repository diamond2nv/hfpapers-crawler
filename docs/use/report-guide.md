# Report Guide — `hfpclawer verify report`

Generate publication-ready verification reports from the Formula Registry.

## Usage

```bash
# LaTeX snippet (standalone .tex document)
hfpclawer verify report <fid>

# Quarto .tex document (for one-click PDF via Quarto)
hfpclawer verify report <fid> --qmd > report.tex
quarto render report.tex --to pdf

# With custom title
hfpclawer verify report <fid> --qmd --title "My Report" > report.tex
```

## Output Modes

### 1. LaTeX snippet (default)

Prints a standalone `.tex` document to stdout with:

- **Basic info table**: FID, LaTeX, dimension, source, tags, reliability grade
- **Verification pipeline**: L1→L5 layer-by-layer results with checkmark/cross
- **CAS equivalence proof**: SymPy ↔ Wolfram Engine algebra comparison (`align*`)
- **Numerical verification**: table of computed vs expected values
- **Publication recommendation**: Grade A/B/C

The output is a self-contained `.tex` file with `documentclass{article}` and `ctex` for Chinese support. Compile it:

```bash
hfpclawer verify report eq:biot-savart > appendix.tex
xelatex appendix.tex
```

Or embed it in an existing paper:

```latex
\input{appendix_verify.tex}
```

### 2. Standalone .tex (`--qmd`)

Generates a `.tex` file using `ctexart` with Liberation Serif layout, ready for direct compilation or Quarto rendering:

```bash
hfpclawer verify report eq:biot-savart --qmd > report.tex
xelatex report.tex                                          # Direct
quarto render report.tex --to pdf                           # Via Quarto
```

## Prerequisites for PDF rendering

### Quarto installation (Chinese-friendly, behind GFW)

```bash
VERSION="1.10.2"
aria2c -x 5 -s 5 "https://ghproxy.net/https://github.com/quarto-dev/quarto-cli/releases/download/v${VERSION}/quarto-${VERSION}-linux-amd64.tar.gz"
tar -xzf quarto-${VERSION}-linux-amd64.tar.gz -C /tmp/
mkdir -p ~/.local/share/quarto
mv /tmp/quarto-${VERSION} ~/.local/share/quarto/${VERSION}
ln -sf ~/.local/share/quarto/${VERSION}/bin/quarto ~/.local/bin/quarto
```

### TinyTeX installation

```bash
quarto install tinytex
export PATH="$HOME/.TinyTeX/bin/x86_64-linux:$PATH"
```

Persist to shell profile:

```bash
echo 'export PATH="$HOME/.TinyTeX/bin/x86_64-linux:$PATH"' >> ~/.bashrc
```

### First-time compilation

The first `quarto render` may take 2–3 minutes as TinyTeX downloads LaTeX packages on demand. Subsequent renders are fast (~15s).

```bash
quarto render report.qmd --to pdf
ls -lh report.pdf
```

## Example workflow

```bash
# 1. Add a formula
hfpclawer verify add eq:magnetic-force "$\mathbf{F} = q(\mathbf{E} + \mathbf{v} \times \mathbf{B})$" \
  --dim "force" --tag electromagnetism --tag lorentz

# 2. Run verification
hfpclawer verify fid eq:magnetic-force

# 3. Generate LaTeX report (for embedding in paper)
hfpclawer verify report eq:magnetic-force > appendix_magnetic.tex

# 4. Generate standalone .tex (for Quarto PDF)
hfpclawer verify report eq:magnetic-force --qmd > appendix.tex
quarto render appendix.tex --to pdf
```

## Reliability Grades

| Grade | Criteria | Meaning |
|-------|----------|---------|
| **A** | All layers passed (6/6) | Ready for publication — dual CAS verification + numeric + dimension + limits |
| **B** | ≥5/6 layers passed | Review non-passing layer(s) before publication |
| **C** | <5/6 layers passed | Re-verify and fix issues before publication |

## Known issues

1. **`\section` vs `ctexart`**: The LaTeX snippet uses `\section` which requires `ctexart` or `article` class. The default preamble includes `ctex`.
2. **Wolfram Engine**: CAS cross-validation requires a running Wolfram Engine Docker container. Without it, L1b is skipped with a note.
3. **Numeric checks**: L2 numeric verification requires `numeric_check` field in the entry — most formulas skip L2 gracefully.
4. **Long LaTeX**: Formulas exceeding ~80 characters may be truncated in table cells. The full LaTeX is still available in the basic info row.

---

## Appendix: Verification Pipeline Layer Reference

*Applicable to hfpclawer ≥ v0.7.3. Future layers marked with †.*

The verification report grades formulas across 6 layers. Each layer targets a specific failure mode and uses an independent toolchain:

| Layer | Name | What it checks | Tool | Failure examples |
|-------|------|----------------|------|------------------|
| **L1** | Symbolic derivation | Parse LaTeX → SymPy → simplify. Catches syntax errors, undefined symbols, divergent integrals. | SymPy | `\sin^2 x + \cos^2 x` → `1` ✅; malformed LaTeX → parse error ❌ |
| **L1b** | CAS cross-validation | Evaluate same LaTeX in SymPy + Wolfram Engine; prove algebraic equivalence via 9 strategies (simplify/expand/together/trigsimp/powsimp/factor/derivative/ratio/numeric_fallback). | SymPy + Wolfram Engine (Docker) | `(x-1)(x+1)` vs `x^2-1` → expand ✅; `\sin^2 x` vs `1-\cos^2 x` → trigsimp ✅ |
| **L2** | Numerical cross-check | Substitute concrete values; compare computed vs expected result within tolerance (5%). | NumPy + SymPy | `q=1.6e-19, E=1, B=0, v=0` → `F=1.6e-19` ✅; off by 10⁶× → micro-to-meter trap ❌ |
| **L3** | Dimensional analysis | Check physical dimension via pint. Verifies the formula's dimension matches its declared quantity (e.g. force → `[M·L·T⁻²]`). | pint | `F=ma` → dimension `[M·L·T⁻²]` ✅; `F=mv` → wrong dimension ❌ |
| **L4** | Physical limits | Symbolic limit tests: far-field (var→∞) should → 0 or constant; near-field singularity detection. | SymPy limit() | `1/r` at r→∞ → 0 ✅; `1/r` at r=0 → diverges ⚠️ |
| **L5** | Singularity detection | AST walker finds denominator zeros, logarithmic branch cuts, and inverse-power singularities. | SymPy preorder_traversal | `\frac{1}{r}` → `1/r` flagged ⚠️; `\log(z-1)` → `log(z-1)` flagged ⚠️ |

### How to interpret the grade

A failed layer does **not** mean the formula is wrong. It means the checker found a signal it couldn't automatically dismiss:

| Report status | Likely meaning |
|--------------|----------------|
| ❌ L5 (singularity) | `1/r` at origin — physically valid but flagged; review annotations needed |
| ❌ L1 (parse) | Typo in LaTeX or unsupported macro (e.g. `\bm` instead of `\mathbf`) |
| ❌ L1b (CAS) | SymPy ↔ Wolfram disagree — genuine discrepancy or simplification path divergence |
| ❌ L3 (dimension) | Unit mismatch — e.g. force formula outputs `[M·L·T⁻¹]` instead of `[M·L·T⁻²]` |

### Future layers (†)

| Layer | Name | Planned capability | Target version |
|-------|------|-------------------|----------------|
| **L6** † | Formal proof | Lean 4 theorem prover integration. Translate verified SymPy expressions into Lean `calc` blocks and discharge via `simp` / `ring` / `field_simp`. | v0.8+ |
| **L7** † | Figure-of-merit | Benchmarked numerical accuracy against published values for given test cases. | v0.9+ |
| **L8** † | Literature coherence | Cross-reference with known results from arXiv/DOI — checks whether the formula's numerical predictions match established experimental/computational baselines. | v1.0+ |
