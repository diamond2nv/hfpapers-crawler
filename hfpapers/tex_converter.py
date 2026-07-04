#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tex_converter.py — arXiv TeX source → Markdown (0 LLM, 0 token)

Converts arXiv tar.gz TeX sources to Markdown while preserving:
  - LaTeX math (inline $...$, display $$...$$)
  - Cross-references (@cite, [ref:label], {#sec:id})
  - Section hierarchy

Two-stage pipeline:
  1. pandoc  (best quality, handles revtex4-class files)
  2. regex   (fallback for LyX-generated / complex preamble)

Usage:
    from hfpapers.tex_converter import convert_tex_sources
    count = convert_tex_sources(to_wiki=True)
"""

import gzip
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("hfpapers.tex_converter")

# ─── Paths ────────────────────────────────────────────

# Resolve relative to project root or config
_BASE_DIR = Path(__file__).resolve().parent.parent
TEX_DIR = _BASE_DIR / "data" / "tex_src"
MD_DIR = _BASE_DIR / "data" / "mds"
WIKI_DIR = Path.home() / "wiki" / "raw" / "papers"


# ─── Result ───────────────────────────────────────────


@dataclass
class ConversionResult:
    arxiv_id: str = ""
    tex_file: str = ""
    md_file: str = ""
    method: str = ""  # "pandoc" | "regex"
    chars: int = 0
    equations: int = 0
    error: str = ""


@dataclass
class BatchSummary:
    total: int = 0
    converted: int = 0
    skipped: int = 0
    failed: int = 0
    results: list = field(default_factory=list)

    def summary_line(self) -> str:
        return (
            f"{self.converted} MD | {self.skipped} skip | {self.failed} fail ({self.total} total)"
        )


# ─── Pandoc Conversion ────────────────────────────────


def _find_pandoc() -> Optional[str]:
    """Locate pandoc binary (bundled with Quarto or system)."""
    candidates = [
        # Quarto bundled (v1.10+)
        "/home/shenli/.local/share/quarto/1.10.2/bin/tools/x86_64/pandoc",
        "/home/shenli/.local/quarto-1.10.2/bin/tools/x86_64/pandoc",
        # System
        "pandoc",
    ]
    for c in candidates:
        try:
            r = subprocess.run([c, "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return c
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _pandoc_convert(tex_path: Path, md_path: Path, pandoc_bin: str) -> Optional[str]:
    """Convert .tex → .md via pandoc. Returns error string or None on success."""
    try:
        r = subprocess.run(
            [pandoc_bin, str(tex_path), "-o", str(md_path),
             "--mathjax", "--wrap=preserve"],
            capture_output=True, text=True, timeout=60,
        )
        if md_path.exists() and md_path.stat().st_size > 100:
            return None  # success
        # Try with raw_tex fallback for LyX files
        r = subprocess.run(
            [pandoc_bin, str(tex_path), "-o", str(md_path),
             "--from", "latex+raw_tex", "--mathjax", "--wrap=preserve"],
            capture_output=True, text=True, timeout=60,
        )
        if md_path.exists() and md_path.stat().st_size > 100:
            return None
        return r.stderr[:200] if r.stderr else "pandoc: output too small"
    except subprocess.TimeoutExpired:
        return "pandoc: timeout (60s)"
    except Exception as e:
        return f"pandoc: {e}"


# ─── Regex Fallback ───────────────────────────────────


_RE_PREAMBLE = re.compile(r"(?s)^.*?\\begin\{document\}")
_RE_POSTAMBLE = re.compile(r"(?s)\\end\{document\}.*$")
_RE_COMMENT = re.compile(r"(?m)^\s*%.*$")
_RE_MAKETITLE = re.compile(r"(?s)\\maketitle.*?\\maketitle")
_RE_SECTION = re.compile(r"\\(?:section|subsection|subsubsection)\*?\{(.*?)\}")
_RE_DISPLAY_MATH = re.compile(r"(?s)\\begin\{(equation|align|eqnarray)\*?\}(.*?)\\end\{\1\*?\}")
_RE_INLINE_MATH = re.compile(r"\$(.+?)\$")
_RE_CITE = re.compile(r"\\cite\{(.*?)\}")
_RE_REF = re.compile(r"\\ref\{(.*?)\}")
_RE_LABEL = re.compile(r"\\label\{(.*?)\}")
_RE_FIGURE = re.compile(r"(?s)\\begin\{figure\*?\}.*?\\end\{figure\*?\}")
_RE_TABLE = re.compile(r"(?s)\\begin\{table\*?\}.*?\\end\{table\*?\}")
_RE_EMPH = re.compile(r"\\textit\{(.*?)\}")
_RE_BOLD = re.compile(r"\\textbf\{(.*?)\}")
_RE_MULTILINE = re.compile(r"\n{3,}")


def _regex_convert(tex_path: Path, md_path: Path) -> Optional[str]:
    """Convert .tex → .md via Python regex. Returns error string or None."""
    try:
        tex = tex_path.read_text(encoding="latin-1")
    except Exception as e:
        return f"read error: {e}"

    # Strip preamble/postamble
    tex = _RE_PREAMBLE.sub("", tex)
    tex = _RE_POSTAMBLE.sub("", tex)
    tex = _RE_COMMENT.sub("", tex)

    # Convert sections
    tex = _RE_SECTION.sub(r"## \1", tex)

    # Preserve display math
    def _wrap_display(m):
        return f"$$\n{m.group(2).strip()}\n$$"
    tex = _RE_DISPLAY_MATH.sub(_wrap_display, tex)

    # Citations and refs
    tex = _RE_CITE.sub(r"[@\1]", tex)
    tex = _RE_REF.sub(r"[ref:\1]", tex)

    # Strip figures/tables (keep caption if present)
    tex = _RE_FIGURE.sub("[figure]", tex)
    tex = _RE_TABLE.sub("[table]", tex)

    # Emphasis
    tex = _RE_EMPH.sub(r"*\1*", tex)
    tex = _RE_BOLD.sub(r"**\1**", tex)

    # Strip LaTeX control sequences that pandoc would handle
    tex = re.sub(r"\\(?:text|mathrm|mathbf|mathcal|mathit|mathbb|mathsf)\{([^}]*)\}", r"\1", tex)

    # Collapse blank lines
    tex = _RE_MULTILINE.sub("\n\n", tex)

    # Filter: keep non-empty lines that are not pure LaTeX commands
    lines = []
    for line in tex.split("\n"):
        s = line.strip()
        if not s:
            continue
        # Skip lines that are pure LaTeX control (no math, no text)
        if s.startswith("\\") and "$" not in s:
            continue
        lines.append(s)

    content = "\n".join(lines)
    md_path.write_text(f"---\nconverted_by: hfpclawer-tex-regex\n---\n\n{content}")
    return None


# ─── Main Pipeline ────────────────────────────────────


def _count_equations(md_text: str) -> int:
    """Count display equations in Markdown output."""
    return len(re.findall(r"\$\$", md_text)) // 2


def convert_one(arxiv_id: str, tex_path: Path, md_path: Path, pandoc_bin: Optional[str]) -> ConversionResult:
    """Convert a single .tex file to .md."""
    result = ConversionResult(arxiv_id=arxiv_id, tex_file=str(tex_path), md_file=str(md_path))

    # Try pandoc first
    if pandoc_bin:
        err = _pandoc_convert(tex_path, md_path, pandoc_bin)
        if err is None:
            result.method = "pandoc"
        else:
            logger.debug(f"pandoc failed for {arxiv_id}: {err}")
            result.error = err

    # Fall back to regex
    if not result.method:
        err = _regex_convert(tex_path, md_path)
        if err is None:
            result.method = "regex"
        else:
            result.error = err
            result.method = "failed"

    if result.method != "failed" and md_path.exists():
        md_text = md_path.read_text()
        result.chars = len(md_text)
        result.equations = _count_equations(md_text)

    return result


def convert_tex_sources(
    tex_dir: Optional[Path] = None,
    md_dir: Optional[Path] = None,
    to_wiki: bool = False,
    arxiv_ids: Optional[list[str]] = None,
) -> BatchSummary:
    """Batch convert arXiv tar.gz TeX sources to Markdown.

    Args:
        tex_dir: Directory with .tar.gz files (default: data/tex_src/)
        md_dir: Output directory (default: data/mds/)
        to_wiki: Also copy to ~/wiki/raw/papers/
        arxiv_ids: Only process these arXiv IDs (default: all)

    Returns:
        BatchSummary with conversion counts.
    """
    tex_dir = tex_dir or TEX_DIR
    md_dir = md_dir or MD_DIR
    md_dir.mkdir(parents=True, exist_ok=True)

    if not tex_dir.exists():
        logger.warning(f"TeX source directory not found: {tex_dir}")
        return BatchSummary()

    pandoc_bin = _find_pandoc()
    if pandoc_bin:
        logger.info(f"pandoc available: {pandoc_bin}")
    else:
        logger.warning("pandoc not found, using regex fallback only")

    summary = BatchSummary()
    processed_ids = set()

    # Determine which archives to process
    patterns = ["*.tar.gz"]
    gz_files = []
    for pat in patterns:
        gz_files.extend(tex_dir.glob(pat))

    if arxiv_ids:
        id_set = set(arxiv_ids)
        def _matches(gz):
            name = gz.name
            aid = name[:-7] if name.endswith(".tar.gz") else gz.stem
            return aid in id_set
        gz_files = [f for f in gz_files if _matches(f)]

    for gz_path in sorted(gz_files):
        # Handle .tar.gz double extension
        name = gz_path.name
        if name.endswith(".tar.gz"):
            arxiv_id = name[:-7]
        else:
            arxiv_id = gz_path.stem

        if arxiv_id in processed_ids:
            continue
        processed_ids.add(arxiv_id)

        summary.total += 1

        # Check if already converted
        existing_mds = list(md_dir.glob(f"{arxiv_id}-*.md"))
        if existing_mds:
            summary.skipped += 1
            continue

        # Extract to temp dir
        try:
            with tempfile.TemporaryDirectory() as tmpd:
                with tarfile.open(gz_path, "r:gz") as tf:
                    tf.extractall(tmpd, filter="data")

                tex_files = sorted(Path(tmpd).rglob("*.tex"))
                if not tex_files:
                    logger.debug(f"No .tex files in {gz_path.name}")
                    summary.skipped += 1
                    continue

                any_converted = False
                for tf_path in tex_files:
                    base = tf_path.stem
                    md_name = f"{arxiv_id}-{base}.md"
                    md_path = md_dir / md_name

                    result = convert_one(arxiv_id, tf_path, md_path, pandoc_bin)
                    if result.method != "failed":
                        any_converted = True
                        summary.converted += 1
                        summary.results.append(result)
                        logger.info(f"  {arxiv_id}/{base}.tex → {md_name} ({result.method}, {result.chars}c, {result.equations}eq)")
                    else:
                        summary.failed += 1
                        logger.warning(f"  {arxiv_id}/{base}.tex → FAILED: {result.error}")

                if not any_converted:
                    summary.skipped += 1

        except Exception as e:
            logger.warning(f"Error processing {gz_path.name}: {e}")
            summary.failed += 1

    # Copy to wiki
    if to_wiki and summary.converted > 0:
        WIKI_DIR.mkdir(parents=True, exist_ok=True)
        for r in summary.results:
            src = md_dir / r.md_file.split("/")[-1]
            if src.exists():
                shutil.copy2(str(src), str(WIKI_DIR / src.name))
        logger.info(f"  Synced {summary.converted} MDs to {WIKI_DIR}")

    return summary


def cli_convert_tex(
    to_wiki: bool = False,
    arxiv_id: Optional[str] = None,
    tex_dir: Optional[Path] = None,
):
    """CLI entry point: convert arXiv tar.gz → formula-preserving Markdown.

    Args:
        to_wiki: Copy results to ~/wiki/raw/papers/
        arxiv_id: Single arXiv ID to process (None = all pending)
        tex_dir: Custom tex_src directory (None = default)
    """
    ids = [arxiv_id] if arxiv_id else None
    summary = convert_tex_sources(to_wiki=to_wiki, arxiv_ids=ids, tex_dir=tex_dir)

    logger.info(f"\n{'=' * 45}")
    logger.info(f"✅ TeX→MD complete: {summary.summary_line()}")
    if summary.results:
        for r in summary.results[:5]:
            logger.info(f"  {r.arxiv_id}: {r.method}, {r.chars}c, {r.equations}eq")
        if len(summary.results) > 5:
            logger.info(f"  ... and {len(summary.results) - 5} more")
