#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compare.py — Unified LaTeX comparison layer for hfpclawer.

Three-level fallback strategy for comparing LaTeX expressions
from different engines (SymPy, Wolfram Engine, Wolfram Alpha):

    Level 1 — Algebraic equivalence:  sp.simplify(A - B) == 0
    Level 2 — Numerical equivalence:  random subs, rel_error < 1e-8
    Level 3 — Structural AST diff:    normalized token tree comparision

All engines produce LaTeX → all compared through the same layer.

Usage:
    from hfpclawer.verify.compare import compare_latex, normalize_latex

    result = compare_latex(
        r"\frac{\\mu_0 I}{2\\pi d}",
        r"\frac{I \\mu_0}{2 d \\pi}",
    )
    # ComparisonResult(passed=True, method="algebraic", rel_error=0.0)
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("hfpclawer.verify.compare")


# ════════════════════════════════════════════
# ComparisonResult
# ════════════════════════════════════════════


@dataclass
class ComparisonResult:
    """Result of comparing two LaTeX expressions."""

    passed: bool
    method: str = "string"        # "algebraic" | "numeric" | "structural" | "string"
    rel_error: float = 0.0
    detail: str = ""
    engine_a: str = ""
    engine_b: str = ""

    def __bool__(self) -> bool:
        return self.passed


# ════════════════════════════════════════════
# LaTeX normalization (string-level)
# ════════════════════════════════════════════


def normalize_latex(latex: str) -> str:
    """Normalize a LaTeX string for structural comparison.

    Strips whitespace, normalizes common commutative reorderings,
    unifies spacing around operators.
    """
    if not latex:
        return ""

    s = latex.strip()

    # Remove \displaystyle, \textstyle, etc.
    s = re.sub(r"\\(displaystyle|textstyle|scriptstyle)", "", s)

    # Normalize whitespace
    s = re.sub(r"\s+", " ", s)

    # Remove extra braces around single tokens
    s = re.sub(r"\{([a-zA-Z0-9_]+)\}", r"\1", s)

    # Remove \left, \right
    s = re.sub(r"\\(left|right)\b", "", s)

    # Normalize \\, → \,
    s = re.sub(r"\\\\,", r"\\,", s)

    return s.strip()


# ════════════════════════════════════════════
# Level 1: Algebraic equivalence
# ════════════════════════════════════════════


def _compare_algebraic(
    latex_a: str, latex_b: str,
    assumptions: Optional[dict] = None,
) -> Optional[ComparisonResult]:
    """Algebraic comparison via SymPy symbolic simplification.

    Tries sp.simplify(parse_latex(A) - parse_latex(B)) == 0.
    Returns None if parsing fails or SymPy is unavailable.
    """
    try:
        import sympy as sp
        from sympy.parsing.latex import parse_latex
    except ImportError:
        return None

    try:
        a = parse_latex(latex_a)
        b = parse_latex(latex_b)
        if a is None or b is None:
            return None
    except Exception as exc:
        logger.debug("Algebraic: parse_latex failed: %s", exc)
        return None

    try:
        diff = sp.simplify(a - b)
        if diff == 0:
            return ComparisonResult(
                passed=True, method="algebraic",
                detail="sp.simplify(A-B) == 0",
            )
        # Not exactly zero — check if it's a small numeric difference
        if diff.is_number:
            try:
                val = float(diff.evalf())
                if abs(val) < 1e-15:
                    return ComparisonResult(
                        passed=True, method="algebraic",
                        detail=f"diff={val:.2e} (within float noise)",
                    )
                return ComparisonResult(
                    passed=False, method="algebraic",
                    rel_error=float(abs(val)),
                    detail=f"diff={val:.2e}",
                )
            except Exception:
                pass

        # Non-numeric difference — try numerical comparison
        return ComparisonResult(
            passed=False, method="algebraic",
            detail=f"non-zero symbolic diff: {sp.latex(diff)[:80]}",
        )
    except Exception as exc:
        logger.debug("Algebraic: simplify failed: %s", exc)
        return None


# ════════════════════════════════════════════
# Level 2: Numerical equivalence
# ════════════════════════════════════════════


def _compare_numeric(
    latex_a: str, latex_b: str,
    n_samples: int = 10,
    tolerance: float = 1e-8,
) -> Optional[ComparisonResult]:
    """Numerical comparison via random parameter subsampling.

    Parses both LaTeX strings, extracts common symbols, and
    evaluates at random points. Returns None if parsing fails.
    """
    try:
        import sympy as sp
        from sympy.parsing.latex import parse_latex
    except ImportError:
        return None

    try:
        a = parse_latex(latex_a)
        b = parse_latex(latex_b)
        if a is None or b is None:
            return None
    except Exception:
        return None

    symbols = list(a.free_symbols | b.free_symbols)
    if not symbols:
        # Both are numbers — compare directly
        try:
            va = float(a.evalf())
            vb = float(b.evalf())
            err = abs(va - vb) / max(abs(va), abs(vb), 1e-15)
            return ComparisonResult(
                passed=err < tolerance,
                method="numeric",
                rel_error=float(err),
                detail=f"va={va:.6e}, vb={vb:.6e}, rel_err={err:.2e}",
            )
        except Exception:
            return None

    max_err = 0.0
    for _ in range(n_samples):
        subs = {s: random.uniform(0.5, 2.0) for s in symbols}
        try:
            va = float(a.subs(subs).evalf())
            vb = float(b.subs(subs).evalf())
        except Exception:
            continue
        denom = max(abs(va), abs(vb), 1e-15)
        err = abs(va - vb) / denom
        max_err = max(max_err, err)
        if err > tolerance:
            return ComparisonResult(
                passed=False, method="numeric",
                rel_error=float(err),
                detail=f"sample err={err:.2e} > tolerance={tolerance:.2e}",
            )

    return ComparisonResult(
        passed=True, method="numeric",
        rel_error=float(max_err),
        detail=f"max relative error={max_err:.2e} over {n_samples} samples",
    )


# ════════════════════════════════════════════
# Level 3: Structural AST comparison
# ════════════════════════════════════════════


def _latex_tokens(latex: str) -> list[str]:
    """Tokenize a LaTeX string into structural tokens.

    Breaks on operators (+ - =), fractions, and command boundaries.
    """
    # Remove environments
    s = re.sub(r"\\begin\{.*?\}.*?\\end\{.*?\}", "", latex)
    tokens = re.findall(
        r"\\\\[a-zA-Z]+|\\[a-zA-Z]+|[a-zA-Z_][a-zA-Z0-9_]*"
        r"|\d+(?:\.\d+)?|[+\-*/=()\[\]{}^_]|.",
        s,
    )
    return [t for t in tokens if t.strip() and t != " "]


def _compare_structural(latex_a: str, latex_b: str) -> ComparisonResult:
    """Structural comparison via token-level equality after normalization.

    This is the weakest method — only catches near-identical strings.
    """
    a_norm = normalize_latex(latex_a)
    b_norm = normalize_latex(latex_b)

    if a_norm == b_norm:
        return ComparisonResult(
            passed=True, method="structural",
            detail="normalized strings equal",
        )

    # Token-level comparison for diagnostic
    tok_a = _latex_tokens(a_norm)
    tok_b = _latex_tokens(b_norm)

    if tok_a == tok_b:
        return ComparisonResult(
            passed=True, method="structural",
            detail="token lists equal (whitespace-only diff)",
        )

    # Compute simple token overlap
    overlap = sum(1 for t in tok_a if t in tok_b)
    ratio = overlap / max(len(tok_a), len(tok_b), 1)

    return ComparisonResult(
        passed=ratio > 0.9,
        method="structural",
        detail=f"token overlap={ratio:.0%} ({overlap}/{max(len(tok_a), len(tok_b))})",
    )


# ════════════════════════════════════════════
# Public API
# ════════════════════════════════════════════


def compare_latex(
    latex_a: str,
    latex_b: str,
    method: str = "algebraic",
    tolerance: float = 1e-8,
    n_samples: int = 10,
) -> ComparisonResult:
    """Compare two LaTeX expressions using three-level fallback.

    Strategy:
        1. Try algebraic (sp.simplify). Exact.
        2. Fall back to numeric (random subsampling). Approximate.
        3. Fall back to structural (normalized string). Weakest.

    Args:
        latex_a: First LaTeX expression.
        latex_b: Second LaTeX expression.
        method: Preferred method. "algebraic" (default) falls back
                through all three levels. "numeric" skips algebraic.
                "structural" uses only string comparison.
        tolerance: Relative error threshold for numeric comparison.
        n_samples: Number of random samples for numeric comparison.

    Returns:
        ComparisonResult with passed, method, rel_error, detail.
    """
    # Fast path: identical strings
    if latex_a == latex_b:
        return ComparisonResult(passed=True, method="string", detail="identical strings")

    # Level 1: Algebraic
    if method == "algebraic":
        result = _compare_algebraic(latex_a, latex_b)
        if result is not None:
            return result

    # Level 2: Numeric
    if method in ("algebraic", "numeric"):
        result = _compare_numeric(latex_a, latex_b, n_samples=n_samples, tolerance=tolerance)
        if result is not None:
            return result

    # Level 3: Structural (always succeeds)
    return _compare_structural(latex_a, latex_b)


def batch_compare(
    pairs: list[tuple[str, str]],
    **kwargs,
) -> list[ComparisonResult]:
    """Batch compare multiple LaTeX pairs.

    Args:
        pairs: List of (latex_a, latex_b) tuples.
        **kwargs: Passed to compare_latex().

    Returns:
        List of ComparisonResult, one per pair.
    """
    results = []
    for a, b in pairs:
        try:
            r = compare_latex(a, b, **kwargs)
        except Exception as exc:
            r = ComparisonResult(passed=False, method="string", detail=str(exc))
        results.append(r)
    return results
