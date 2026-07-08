#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
consistency.py — LaTeX ↔ SymPy roundtrip consistency check.

Verifies that a LaTeX formula can be roundtripped through SymPy:
    latex → sp.parse_latex() → sp.simplify() → sp.latex() → compare

This catches:
  - LaTeX parser failures (antlr4 issues, malformed LaTeX)
  - SymPy simplification that changes the expression structure
  - Ambiguous implicit multiplication (d\\pi vs d{\\pi})

Usage:
    from hfpclawer.verify.consistency import check_latex, check_roundtrip

    result = check_latex(r"\\frac{\\mu_0 I}{2\\pi d}")
    # ConsistencyResult(passed=True, input_latex=..., sympy_latex=..., method=...)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("hfpclawer.verify.consistency")


# ════════════════════════════════════════════
# ConsistencyResult
# ════════════════════════════════════════════


@dataclass
class ConsistencyResult:
    """Result of a LaTeX ↔ SymPy roundtrip check."""

    passed: bool
    input_latex: str
    sympy_latex: str = ""
    method: str = ""          # "roundtrip" | "direct" | "failed"
    detail: str = ""
    symbol_count: int = 0

    def __bool__(self) -> bool:
        return self.passed


# ════════════════════════════════════════════
# Symbol name sanitization
# ════════════════════════════════════════════

# Wolfram built-in names that conflict with common physics symbols
WOLFRAM_RESERVED = {
    "I", "E", "N", "D", "C", "K", "O",
    "Pi", "Epsilon", "Gamma", "Lambda", "Theta",
    # Common Wolfram built-in patterns
    "Abs", "Cos", "Sin", "Tan", "Log", "Exp", "Sqrt",
    "Integrate", "Sum", "Product", "Limit", "DSolve",
    "Plus", "Times", "Power", "List", "Rule", "RuleDelayed",
    "True", "False", "Null", "None", "All",
}

# Common physics subscript symbols in SymPy (braces format) → Wolfram-safe names
SUBSCRIPT_RENAME: dict[str, str] = {
    # mu_{0} → mu0, h_{bar} → hbar, etc.
}


def sanitize_symbol_name(name: str) -> str:
    """Convert a SymPy symbol name to a Wolfram-safe name.

    Handles:
      - Subscript notation: mu_{0} → mu0, mu_{B} → muB
      - Wolfram reserved: I → I0, E → E0
      - Special chars: α → alpha, β → beta
    """
    s = name.strip()

    # Remove LaTeX-style subscripts: mu_{0} → mu0
    s = s.replace("{", "").replace("}", "")
    s = s.replace("_", "")

    # Check Wolfram reserved conflict
    if s in WOLFRAM_RESERVED:
        s = s + "_phys"  # I → I_phys

    return s


def sanitize_expression(expr) -> tuple:
    """Rename all symbols in a SymPy expression to Wolfram-safe names.

    Returns:
        (sanitized_expr, rename_map) where rename_map = {old_sym: new_sym}
    """
    import sympy as sp

    rename_map = {}
    for sym in expr.free_symbols:
        new_name = sanitize_symbol_name(sym.name)
        if new_name != sym.name:
            rename_map[sym] = sp.Symbol(new_name)

    if not rename_map:
        return expr, {}

    sanitized = expr.subs(rename_map)
    return sanitized, rename_map


# ════════════════════════════════════════════
# Roundtrip check
# ════════════════════════════════════════════


def check_latex(latex: str) -> ConsistencyResult:
    """Check if a LaTeX formula can be parsed and roundtripped through SymPy.

    Steps:
      1. sp.parse_latex(latex) → SymPy expression
      2. sp.simplify(expr) → simplified expression
      3. sp.latex(expr) → output LaTeX
      4. Normalize comparison: input vs output

    Returns:
        ConsistencyResult with pass/fail and diagnostic info.
    """
    try:
        import sympy as sp
        from sympy.parsing.latex import parse_latex
    except ImportError:
        return ConsistencyResult(
            passed=False,
            input_latex=latex,
            method="failed",
            detail="sympy not available",
        )

    if not latex or not latex.strip():
        return ConsistencyResult(
            passed=False, input_latex=latex,
            method="failed", detail="empty LaTeX",
        )

    try:
        expr = parse_latex(latex)
        if expr is None:
            return ConsistencyResult(
                passed=False, input_latex=latex,
                method="failed", detail="parse_latex returned None",
            )
    except Exception as exc:
        return ConsistencyResult(
            passed=False, input_latex=latex,
            method="failed", detail=f"parse_latex error: {exc}",
        )

    # Count symbols
    symbol_count = len(expr.free_symbols)

    # Generate output LaTeX from SymPy
    try:
        sympy_latex = sp.latex(sp.simplify(expr))
    except Exception as exc:
        return ConsistencyResult(
            passed=False, input_latex=latex,
            method="failed", detail=f"sp.latex error: {exc}",
            symbol_count=symbol_count,
        )

    # Compare normalized input vs output
    from hfpclawer.verify.compare import compare_latex, normalize_latex

    # Fast path: normalized equality
    if normalize_latex(latex) == normalize_latex(sympy_latex):
        return ConsistencyResult(
            passed=True,
            input_latex=latex,
            sympy_latex=sympy_latex,
            method="roundtrip",
            detail="input == SymPy roundtrip (exact)",
            symbol_count=symbol_count,
        )

    # Structural comparison (handles commutative reordering, minor formatting diff)
    result = compare_latex(latex, sympy_latex, method="algebraic")

    method = f"roundtrip-{result.method}"
    return ConsistencyResult(
        passed=result.passed,
        input_latex=latex,
        sympy_latex=sympy_latex,
        method=method,
        detail=f"SymPy roundtrip: {result.detail}" if result.passed
               else f"SymPy roundtrip mismatch: {result.detail}",
        symbol_count=symbol_count,
    )


def check_batch(latex_list: list[str]) -> list[ConsistencyResult]:
    """Batch check a list of LaTeX formulas."""
    return [check_latex(l) for l in latex_list]


# ════════════════════════════════════════════
# SymPy → Wolfram code conversion
# ════════════════════════════════════════════


def sympy_to_wolfram(expr, use_export_string: bool = False) -> tuple[str, dict]:
    """Convert a SymPy expression to Wolfram language code.

    Handles:
      - Symbol renaming for Wolfram compatibility
      - Integral/Derivative conversion
      - TeXForm export via ExportString when needed

    Args:
        expr: SymPy expression.
        use_export_string: If True, wrap in ExportString[TeXForm[...]]
                           for clean LaTeX output (slower).

    Returns:
        (wolfram_code_str, rename_map)
    """
    from sympy.printing.mathematica import mathematica_code

    # 1. Sanitize symbol names for Wolfram compatibility
    sanitized, rename_map = sanitize_expression(expr)

    # 2. Generate Mathematica code
    code = mathematica_code(sanitized)

    # 3. Handle Hold[] wrapper for unevaluated expressions
    # (Integrals, derivatives are wrapped in Hold[] by mathematica_code)
    if code.startswith("Hold["):
        code = code[5:-1]  # Strip Hold[] -> just the integral expression

    # 4. Optionally wrap in TeXForm export
    if use_export_string:
        code = f"ExportString[TeXForm[{code}], \"Text\"]"

    return code, rename_map


def wolfram_to_sympy(wolfram_output: str):
    """Parse Wolfram output back to a SymPy expression.

    Handles:
      - TeXForm[expr] wrapping
      - ConditionalExpression extraction
      - Null stripping
      - LaTeX → SymPy parsing

    Returns:
        SymPy expression or None if parsing fails.
    """
    try:
        from sympy.parsing.latex import parse_latex
    except ImportError:
        return None

    s: str = wolfram_output.strip()

    # Strip Null (WolframScript always appends)
    s = s.replace("Null", "").strip()

    # Strip \fbox{$...$} wrapping (Wolfram's LaTeX export format)
    if s.startswith("\\fbox{$") and s.endswith("$}"):
        s = s[7:-2]

    # Strip TeXForm[...] wrapper from gsnv-style output
    if s.startswith("TeXForm[") and s.endswith("]"):
        s = s[8:-1]

    # Strip ConditionalExpression — take the first argument
    if s.startswith("ConditionalExpression[") and s.endswith("]"):
        depth = 1
        for i, ch in enumerate(s[22:], 22):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    s = s[22:i]
                    break

    # Try parsing as LaTeX
    if s.startswith("\\"):
        try:
            return parse_latex(s)
        except Exception:
            pass

    return None
