# Report Guide — `hfpclawer verify report`

Generate publication-ready verification reports from the Formula Registry.

## Usage

```bash
# LaTeX snippet (standalone .tex document)
hfpclawer verify report <fid>

# Quarto .qmd document (for one-click PDF via Quarto)
hfpclawer verify report <fid> --qmd > report.qmd

# With custom title
hfpclawer verify report <fid> --qmd --title "My Report" > report.qmd
```

## Output Modes

### 1. LaTeX snippet (default)

Prints a standalone `.tex` document to stdout with:

- **Basic info table**: FID, LaTeX, dimension, source, tags, reliability grade
- **Verification pipeline**: L1→L5 layer-by-layer results with emoji status
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

### 2. Quarto .qmd (`--qmd`)

Generates a full Quarto `.qmd` document with:

- YAML frontmatter (ctexart + Liberation Serif + booktabs)
- Validation body wrapped in `{=latex}` raw block
- Ready for `quarto render --to pdf`

```bash
hfpclawer verify report eq:biot-savart --qmd > appendix.qmd
quarto render appendix.qmd --to pdf
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

# 4. Generate Quarto .qmd (for standalone PDF)
hfpclawer verify report eq:magnetic-force --qmd > appendix.qmd
quarto render appendix.qmd --to pdf
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
