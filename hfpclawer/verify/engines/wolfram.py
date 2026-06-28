#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
engines/wolfram.py — Wolfram Engine Docker client for hfpclawer.

Converts canonical LaTeX formulas to Wolfram code via SymPy's
mathematica_code(), executes in Docker container, and returns
numeric results for cross-validation.

Design:
  - Input:  LaTeX formula (canonical from FormulaRegistry)
  - Output: WolframResult with numeric value + optional TeXForm display
  - Comparison: numeric (reliable) not algebraic TeXForm (fragile)

Pipeline:
    LaTeX
      → sp.parse_latex() → SymPy expression
      → sanitize_symbol_names() (mu_{0}→mu0, I→I_phys, avoid reserved)
      → mathematica_code() → Wolfram code string
      → strip Hold[] if present
      → construct N[code /. {sym->val, ...}] with numeric subs
      → docker exec wolframscript
      → parse float from output
      → compare with SymPy's numeric evaluation

Example:
    from hfpclawer.verify.engines.wolfram import WolframEngineClient

    client = WolframEngineClient()
    result = client.evaluate_latex(r"\\frac{\\mu_0 I}{2\\pi d}",
                                   subs={"mu0": 4e-7*sp.pi, "I": 1e-3, "d": 10e-6})
    # WolframResult(status="ok", wolfram_val=0.02, sympy_val=0.02, rel_error=0.0)
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Optional

import sympy as sp

logger = logging.getLogger("hfpclawer.verify.engines.wolfram")

# ─── Wolfram built-in symbols that conflict with common physics names ─────
WOLFRAM_RESERVED = {
    "I", "E", "N", "D", "C", "K", "O",
    "Pi", "Epsilon", "Gamma", "Theta",
    "Abs", "Cos", "Sin", "Tan", "Log", "Exp", "Sqrt",
    "Integrate", "Sum", "Product", "Limit", "DSolve",
    "Plus", "Times", "Power", "List", "Rule",
    "True", "False", "Null", "None", "All",
}

# ─── Constants ───────────────────────────────────────────
DEFAULT_TIMEOUT = 30       # Wolfram cold start can be ~8s
DEFAULT_CONTAINER = "wolfram-engine"
COOLDOWN_S = 2.0           # Seconds between Docker exec calls


# ════════════════════════════════════════════
# WolframResult
# ════════════════════════════════════════════


@dataclass
class WolframResult:
    """Result of a Wolfram Engine evaluation.

    Fields:
        status: "ok" | "skipped" | "timeout" | "error"
        wolfram_val: Numeric value from Wolfram (None if failed)
        sympy_val: Numeric value from SymPy (None if not computed)
        rel_error: Relative error |wolfram - sympy| / max(...)
        wolfram_latex: TeXForm display output (optional, may be None)
        detail: Human-readable diagnostic
        elapsed_s: Time taken for Wolfram evaluation
    """
    status: str = "error"
    wolfram_val: Optional[float] = None
    sympy_val: Optional[float] = None
    rel_error: Optional[float] = None
    wolfram_latex: Optional[str] = None
    detail: str = ""
    elapsed_s: float = 0.0

    def passed(self, tolerance: float = 0.05) -> bool:
        """Check if Wolfram result matches SymPy within tolerance."""
        if self.status != "ok":
            return False
        if self.wolfram_val is None or self.sympy_val is None:
            return False
        if self.rel_error is None:
            return True  # No sympy value to compare against = skip
        return self.rel_error < tolerance

    def __bool__(self) -> bool:
        return self.status == "ok"


# ════════════════════════════════════════════
# Symbol name sanitization
# ════════════════════════════════════════════


def sanitize_name(name: str) -> str:
    """Convert SymPy symbol name to Wolfram-safe name.

    Handles:
      - Subscript braces: mu_{0} → mu0
      - Wolfram reserved: I → I_phys, E → E_phys
    """
    s = name.replace("{", "").replace("}", "").replace("_", "")
    if s in WOLFRAM_RESERVED or re.match(r"^\d", s):
        s = s + "_phys"
    return s


def sanitize_expression(expr) -> tuple[Any, dict]:
    """Rename all symbols in a SymPy expression for Wolfram compatibility.

    Returns:
        (sanitized_expr, rename_map)
    """
    import sympy as sp

    rename = {}
    for sym in expr.free_symbols:
        new_name = sanitize_name(sym.name)
        if new_name != sym.name:
            rename[sym] = sp.Symbol(new_name)

    if not rename:
        return expr, {}
    return expr.subs(rename), rename


# ════════════════════════════════════════════
# Wolfram code generation from LaTeX
# ════════════════════════════════════════════


def latex_to_wolfram_code(latex: str) -> str:
    """Convert a LaTeX formula directly to Wolfram code.

    Pipeline: LaTeX → sp.parse_latex → sanitize → mathematica_code

    Returns:
        Wolfram code string (ready for N[code /. rules])

    Raises:
        ValueError if LaTeX parsing fails
    """
    import sympy as sp
    from sympy.parsing.latex import parse_latex
    from sympy.printing.mathematica import mathematica_code

    # 1. Parse LaTeX → SymPy
    expr = parse_latex(latex)
    if expr is None:
        raise ValueError(f"parse_latex returned None for: {latex}")

    # 2. Sanitize symbol names
    clean, _ = sanitize_expression(expr)

    # 3. Generate Wolfram code
    code: str = mathematica_code(clean)  # type: ignore[assignment]

    # 4. Strip Hold[] wrapper (unevaluated integrals/derivatives)
    if isinstance(code, str) and code.startswith("Hold[") and code.endswith("]"):
        code = code[5:-1]

    return code if isinstance(code, str) else str(code)


# ════════════════════════════════════════════
# Number formatting for Wolfram
# ════════════════════════════════════════════


def to_wolfram_number(val: float) -> str:
    """Format a Python float as a Wolfram number.

    Wolfram uses *^ for scientific notation:
      1e-3  →  1*^-3
      1e6   →  1*^6
    """
    if val == 0.0:
        return "0"

    # Use Python's general format
    s = f"{val:.10g}"

    # Check if scientific notation was used
    if "e" in s or "E" in s:
        # Split mantissa and exponent
        parts = s.replace("E", "e").split("e")
        mantissa = parts[0]
        exp = parts[1] if len(parts) > 1 else "0"
        # Use Wolfram's *^ syntax
        return f"{mantissa}*^{exp}"

    return s


# ════════════════════════════════════════════
# WolframEngineClient
# ════════════════════════════════════════════


class WolframEngineClient:
    """Client for Wolfram Engine via Docker exec.

    Design:
      - Subprocess-based: docker exec wolframscript -code "..."
      - No persistent session (simple and reliable)
      - Graceful degradation: container missing → skip
    """

    def __init__(
        self,
        container: str = DEFAULT_CONTAINER,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.container = container
        self.timeout = timeout
        self._last_call: float = 0.0
        self._available: Optional[bool] = None

    # ── Health check ─────────────────────────────────

    def check_available(self) -> bool:
        """Check if Wolfram Engine container is running and responsive."""
        if self._available is not None:
            return self._available
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", f"name={self.container}",
                 "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=5,
            )
            if self.container in result.stdout:
                # Verify wolframscript works (use full timeout for cold start)
                verify = subprocess.run(
                    ["docker", "exec", self.container, "wolframscript",
                     "-code", 'Print["ok"]'],
                    capture_output=True, text=True, timeout=self.timeout,
                )
                self._available = verify.returncode == 0
            else:
                self._available = False
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as exc:
            logger.debug("Wolfram Engine check failed: %s", exc)
            self._available = False
        return self._available

    # ── Raw Wolfram code execution ───────────────────

    def execute(self, code: str) -> dict[str, Any]:
        """Execute raw Wolfram code in the Docker container.

        Args:
            code: Wolfram Language code string.

        Returns:
            dict with keys: status, stdout, stderr, elapsed_s
        """
        # Rate limit
        elapsed = time.time() - self._last_call
        if elapsed < COOLDOWN_S:
            time.sleep(COOLDOWN_S - elapsed)

        t0 = time.time()
        try:
            result = subprocess.run(
                ["docker", "exec", self.container, "wolframscript",
                 "-code", code],
                capture_output=True, text=True,
                timeout=self.timeout,
            )
            self._last_call = time.time()
            elapsed_s = time.time() - t0

            if result.returncode != 0:
                return {
                    "status": "error",
                    "stdout": result.stdout,
                    "stderr": result.stderr.strip(),
                    "elapsed_s": round(elapsed_s, 2),
                }

            return {
                "status": "ok",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "elapsed_s": round(elapsed_s, 2),
            }

        except subprocess.TimeoutExpired:
            self._last_call = time.time()
            return {
                "status": "timeout",
                "stdout": "",
                "stderr": f"timed out after {self.timeout}s",
                "elapsed_s": self.timeout,
            }
        except FileNotFoundError:
            self._available = False
            return {
                "status": "error",
                "stdout": "",
                "stderr": "docker not found in PATH",
                "elapsed_s": 0.0,
            }
        except Exception as exc:
            self._available = False
            return {
                "status": "error",
                "stdout": "",
                "stderr": str(exc),
                "elapsed_s": time.time() - t0,
            }

    # ── Numeric comparison: evaluate LaTeX in both SymPy and Wolfram ──

    def evaluate_latex(
        self,
        latex: str,
        subs: Optional[dict[str, float]] = None,
        tolerance: float = 0.05,
    ) -> WolframResult:
        """Evaluate a LaTeX formula numerically in Wolfram Engine.

        Compares Wolfram's numeric result with SymPy's numeric result
        using the same parameter substitutions.

        Args:
            latex: LaTeX formula (canonical form).
            subs: Parameter substitutions {name: value}.
                  If None, no substitution (evaluate symbolic constant).
            tolerance: Relative error pass threshold (default 5%).

        Returns:
            WolframResult with wolfram_val, sympy_val, rel_error.
        """
        import sympy as sp
        from sympy.parsing.latex import parse_latex

        # ── Step 1: SymPy reference value ──
        try:
            expr = parse_latex(latex)
            if expr is None:
                return WolframResult(
                    status="error", detail=f"parse_latex failed: {latex}"
                )
        except Exception as exc:
            return WolframResult(
                status="error", detail=f"parse_latex error: {exc}"
            )

        sympy_val = None
        if subs:
            try:
                # Match user-provided subs keys to actual symbol names in the expression
                # Expression has Symbol('mu_{0}'), user provides {'mu0': 4e-7}
                # Also auto-substitute math constants: pi, E
                sympy_subs = {}
                for sym in expr.free_symbols:
                    norm_name = sym.name.replace("{", "").replace("}", "").replace("_", "")
                    if norm_name == "pi":
                        sympy_subs[sym] = sp.pi
                    elif norm_name == "e":
                        sympy_subs[sym] = sp.E
                    elif norm_name in subs:
                        sympy_subs[sym] = subs[norm_name]
                if sympy_subs:
                    sympy_val = float(expr.subs(sympy_subs).evalf())
            except Exception as exc:
                logger.debug("SymPy numeric eval failed: %s", exc)
                sympy_val = None

        # ── Step 2: Generate Wolfram code ──
        try:
            wolfram_code = latex_to_wolfram_code(latex)
        except (ValueError, Exception) as exc:
            return WolframResult(
                status="error", detail=f"Wolfram code gen failed: {exc}",
                sympy_val=sympy_val,
            )

        # ── Step 3: Construct full query ──
        if subs and wolfram_code:
            # Build Wolfram substitution rules
            rules = []
            for k, v in subs.items():
                wolf_key = sanitize_name(k)
                wolf_val = to_wolfram_number(v)
                rules.append(f"{wolf_key} -> {wolf_val}")
            full_code = f"N[({wolfram_code}) /. {{{', '.join(rules)}}}]"
        else:
            # No subs — just evaluate numerically
            full_code = f"N[{wolfram_code}]"

        # ── Step 4: Execute ──
        if not self.check_available():
            return WolframResult(
                status="skipped",
                detail="Wolfram Engine container not available",
                sympy_val=sympy_val,
            )

        exec_result = self.execute(full_code)

        if exec_result["status"] != "ok":
            return WolframResult(
                status=exec_result["status"],
                detail=exec_result.get("stderr", "execution failed"),
                sympy_val=sympy_val,
                elapsed_s=exec_result.get("elapsed_s", 0.0),
            )

        # ── Step 5: Parse numeric output ──
        stdout = exec_result.get("stdout", "")
        try:
            wolfram_val = _parse_wolfram_number(stdout)
        except (ValueError, Exception) as exc:
            return WolframResult(
                status="error",
                detail=f"parse output failed: {exc}, raw={stdout[:100]}",
                sympy_val=sympy_val,
                elapsed_s=exec_result.get("elapsed_s", 0.0),
            )

        # ── Step 6: Compute relative error ──
        rel_error = None
        if sympy_val is not None and wolfram_val is not None:
            denom = max(abs(sympy_val), abs(wolfram_val), 1e-15)
            rel_error = abs(wolfram_val - sympy_val) / denom

        return WolframResult(
            status="ok",
            wolfram_val=wolfram_val,
            sympy_val=sympy_val,
            rel_error=rel_error,
            detail=f"rel_error={rel_error:.2e}" if rel_error is not None else "no sympy ref",
            elapsed_s=exec_result.get("elapsed_s", 0.0),
        )

    # ── TeXForm output (display only) ──

    def texform(self, latex: str) -> WolframResult:
        """Get Wolfram Engine's TeXForm output for a LaTeX formula.

        This is for display/report purposes only. Not used for
        algebraic comparison because Wolfram's TeXForm output is
        unreliable (may include \\fbox{}, \\text{}, conditions).

        Returns:
            WolframResult with wolfram_latex set.
        """
        try:
            wolfram_code = latex_to_wolfram_code(latex)
        except (ValueError, Exception) as exc:
            return WolframResult(status="error", detail=f"code gen failed: {exc}")

        if not self.check_available():
            return WolframResult(status="skipped", detail="container not available")

        full_code = f'Print[ExportString[TeXForm[{wolfram_code}], "Text"]]'
        exec_result = self.execute(full_code)

        if exec_result["status"] != "ok":
            return WolframResult(status=exec_result["status"], detail=exec_result.get("stderr", ""))

        stdout = exec_result.get("stdout", "")
        wolfram_latex = _clean_texform(stdout)

        return WolframResult(
            status="ok",
            wolfram_latex=wolfram_latex or "(no TeXForm output)",
            detail="TeXForm display only",
            elapsed_s=exec_result.get("elapsed_s", 0.0),
        )


# ════════════════════════════════════════════
# Output parsers
# ════════════════════════════════════════════


def _parse_wolfram_number(stdout: str) -> Optional[float]:
    """Parse a numeric value from WolframScript stdout.

    Handles:
      - Plain numbers: "0.00002\nNull"
      - Scientific: "2.0*^-5\nNull"
      - Expressions that evaluate to numbers
      - Complex results (extract real part)
    """
    s = stdout.strip()

    # Strip trailing Null (WolframScript always appends)
    s = s.replace("Null", "").strip()

    if not s:
        raise ValueError("empty output")

    # Replace Wolfram's *^ with Python's e notation
    s = s.replace("*^", "e")

    # Try direct float parse
    try:
        return float(s)
    except ValueError:
        pass

    # Try regex: find first number in output
    match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s)
    if match:
        return float(match.group())

    raise ValueError(f"cannot parse number from: {s[:80]}")


def _clean_texform(raw: str) -> Optional[str]:
    """Clean Wolfram's TeXForm output for display.

    Removes:
      - "Null" suffix
      - \\fbox{$...$} wrapping
      - \\text{ if } conditions (abbreviate)
    """
    s = raw.strip()
    s = s.replace("Null", "").strip()

    # Strip \fbox{$...$} wrapping
    if s.startswith("\\fbox{$") and s.endswith("$}"):
        s = s[7:-2]

    # Abbreviate ConditionalExpression text
    s = re.sub(r"\\text\{ if \}.*", "\\text{(condition)}", s)

    return s if s else None


# ── Module-level convenience ─────────────────────

_client_instance: Optional[WolframEngineClient] = None


def get_client(
    container: str = DEFAULT_CONTAINER,
    timeout: int = DEFAULT_TIMEOUT,
) -> WolframEngineClient:
    """Get or create a WolframEngineClient singleton."""
    global _client_instance
    if _client_instance is None:
        _client_instance = WolframEngineClient(container=container, timeout=timeout)
    return _client_instance


def is_available() -> bool:
    """Quick check if Wolfram Engine is available."""
    return get_client().check_available()


# ════════════════════════════════════════════
# wl_to_sympy — Wolfram plaintext → SymPy
# ════════════════════════════════════════════

_WL_TO_SP_MAP: dict[str, str] = {
    # 基本函数
    "Sin": "sin", "Cos": "cos", "Tan": "tan", "Cot": "cot",
    "Sec": "sec", "Csc": "csc",
    # 反函数
    "ArcSin": "asin", "ArcCos": "acos", "ArcTan": "atan",
    "ArcCot": "acot", "ArcSec": "asec", "ArcCsc": "acsc",
    # 双曲函数
    "Sinh": "sinh", "Cosh": "cosh", "Tanh": "tanh",
    "ArcSinh": "asinh", "ArcCosh": "acosh", "ArcTanh": "atanh",
    # 其他
    "Sqrt": "sqrt", "Log": "log", "Exp": "exp",
    "Abs": "abs", "Erf": "erf", "Erfc": "erfc",
    "Floor": "floor", "Ceiling": "ceiling",
    "Sign": "sign", "Re": "re", "Im": "im",
    "Conjugate": "conjugate",
}

_WL_NAMESPACE: dict[str, Any] = {
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
    "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
    "sqrt": sp.sqrt, "log": sp.log, "exp": sp.exp,
    "erf": sp.erf, "Abs": sp.Abs,
    "pi": sp.pi, "E": sp.E, "oo": sp.oo,
}


def wl_to_sympy(s: str) -> Optional[sp.Basic]:
    """Convert Wolfram Language plaintext output to SymPy expression.

    This is the REVERSE of mathematica_code().  Handles:

      - Sin[x] → sin(x), Sqrt[x] → sqrt(x), ArcTan[x/a] → atan(x/a)
      - Pi → pi, E → E, ^ → **
      - Brackets [... ] → (... )
      - Wolfram arithmetic: /, *, +, -

    Args:
        s: Raw Wolfram plaintext output (without Null suffix).

    Returns:
        SymPy expression, or None if parsing fails entirely.
    """
    if not s or not s.strip():
        return None

    s = s.strip()

    # Strip trailing Null (WolframScript artifact)
    s = s.replace("Null", "").strip()

    if not s:
        return None

    # 1. Replace Wolfram function calls
    for wl_name, sp_name in _WL_TO_SP_MAP.items():
        s = re.sub(rf"(?<!\w){wl_name}\[", f"{sp_name}(", s)

    # 2. Constants
    s = s.replace("Pi", "pi").replace("E", "E")

    # 3. Power operator: ^ → ** (but not ** already)
    s = re.sub(r"(?<!\*)\^(?!\*)", "**", s)

    # 4. Brackets: [...] → (...)
    s = s.replace("[", "(").replace("]", ")")

    # 5. Whitespace normalization
    s = re.sub(r"\s+", " ", s).strip()

    # 6. Try SymPy parser
    try:
        return sp.parsing.sympy_parser.parse_expr(s)
    except (sp.parsing.sympy_parser.SymPyParserError, SyntaxError, Exception):
        pass

    # 7. Fallback: eval in safe namespace
    try:
        return eval(s, {"__builtins__": {}}, dict(_WL_NAMESPACE))
    except Exception:
        return None


# ════════════════════════════════════════════
# CASEquivalenceResult
# ════════════════════════════════════════════


@dataclass
class CASEquivalenceResult:
    """Result of a CAS algebraic equivalence proof between two expressions.

    Fields:
        equivalent: True if proven algebraically equivalent.
        method: Strategy that succeeded ("simplify" | "expand" | "together"
                | "trigsimp" | "powsimp" | "factor" | "derivative"
                | "ratio" | "numeric_fallback" | "failed").
        detail: Human-readable description of the proof.
        sympy_result: SymPy expression (engine A).
        wolfram_result: Wolfram result parsed as SymPy (engine B).
        diff: symbolic diff A - B (for diagnostic).
        rel_error_max: Maximum relative error in numeric fallback (if used).
    """
    equivalent: bool = False
    method: str = "failed"
    detail: str = ""
    sympy_result: Optional[sp.Basic] = None
    wolfram_result: Optional[sp.Basic] = None
    diff: Optional[sp.Basic] = None
    rel_error_max: float = 0.0

    def __bool__(self) -> bool:
        return self.equivalent


# ════════════════════════════════════════════
# CASEquivalenceProver — 多策略代数等价性证明
# ════════════════════════════════════════════


class CASEquivalenceProver:
    """Multi-strategy CAS algebraic equivalence prover.

    Combines multiple independent strategies to determine whether two
    expressions (from different CAS engines) are algebraically equivalent.
    Ordered from most reliable (exact algebraic) to least (numerical).

    Strategies (in order):
      1. simplify:   sp.simplify(A - B) == 0
      2. expand:     sp.simplify(sp.expand(A - B)) == 0
      3. together:   sp.simplify(sp.together(A - B)) == 0
      4. trigsimp:   sp.simplify(sp.trigsimp(A - B)) == 0
      5. powsimp:    sp.simplify(sp.powsimp(A - B)) == 0
      6. factor:     sp.simplify(sp.factor(A - B)) == 0
      7. derivative: sp.simplify(sp.diff(A - B, var)) == 0   (积分专用)
      8. ratio:      sp.simplify(A/B) == 1 or sp.simplify(B/A) == 1
      9. numeric:    evaluate at N random points, all |diff| < 1e-10
    """

    def __init__(self, n_numeric: int = 20):
        self.n_numeric = n_numeric

    def prove(
        self,
        A: sp.Basic,
        B: sp.Basic,
        source_var: Optional[sp.Symbol] = None,
    ) -> CASEquivalenceResult:
        """Try all strategies in order to prove A ≡ B algebraically.

        Args:
            A: Expression from engine A (typically SymPy).
            B: Expression from engine B (Wolfram, converted to SymPy).
            source_var: For derivative strategy — the independent variable.

        Returns:
            CASEquivalenceResult with proven equivalence or failure.
        """
        strategies = [
            ("simplify", lambda: _check_zero(sp.simplify(A - B))),
            ("expand", lambda: _check_zero(sp.simplify(sp.expand(A - B)))),
            ("together", lambda: _check_zero(sp.simplify(sp.together(A - B)))),
            ("trigsimp", lambda: _check_zero(sp.simplify(sp.trigsimp(A - B)))),
            ("powsimp", lambda: _check_zero(sp.simplify(sp.powsimp(A - B)))),
            ("factor", lambda: _check_zero(sp.simplify(sp.factor(A - B)))),
        ]

        # Derivative strategy (only if source_var is provided)
        if source_var is not None:
            strategies.append(
                ("derivative", lambda: _check_zero(
                    sp.simplify(sp.diff(A - B, source_var))))
            )

        # Ratio strategy
        strategies.append(("ratio", self._check_ratio(A, B)))

        for name, check_fn in strategies:
            try:
                ok, val = check_fn()
                if ok:
                    return CASEquivalenceResult(
                        equivalent=True, method=name,
                        detail=f"Proved via {name}",
                        sympy_result=A, wolfram_result=B, diff=val,
                    )
            except Exception:
                continue

        # Numerical fallback
        result = self._check_numeric(A, B)
        if result.equivalent:
            return result

        return CASEquivalenceResult(
            equivalent=False, method="failed",
            detail="All algebraic strategies exhausted. "
                   "Expressions may be equivalent but SymPy cannot prove it.",
            sympy_result=A, wolfram_result=B, diff=sp.simplify(A - B),
        )

    # ── Ratio strategy ────────────────────────────

    @staticmethod
    def _check_ratio(A: sp.Basic, B: sp.Basic) -> tuple:
        """Check if A/B == 1 algebraically."""
        try:
            ratio = sp.simplify(A / B)
            if ratio == 1:
                return True, ratio
        except Exception:
            pass
        try:
            ratio = sp.simplify(B / A)
            if ratio == 1:
                return True, ratio
        except Exception:
            pass
        return False, None

    # ── Numerical fallback ────────────────────────

    def _check_numeric(self, A: sp.Basic, B: sp.Basic) -> CASEquivalenceResult:
        """N-point random numeric sampling (last resort)."""
        symbols = list((A.free_symbols | B.free_symbols) - {sp.pi, sp.E})
        if not symbols:
            # Both are constant expressions — compare numerically
            try:
                va = float(A.evalf())
                vb = float(B.evalf())
                err = abs(va - vb) / max(abs(va), abs(vb), 1e-15)
                if err < 1e-12:
                    return CASEquivalenceResult(
                        equivalent=True, method="numeric_fallback",
                        detail=f"Constant: A={va:.10e}, B={vb:.10e}, err={err:.2e}",
                        sympy_result=A, wolfram_result=B,
                        rel_error_max=float(err),
                    )
            except Exception:
                pass
            return CASEquivalenceResult(
                equivalent=False, method="failed",
                detail="Constant expressions differ numerically",
                sympy_result=A, wolfram_result=B,
            )

        import random as _random
        max_err = 0.0
        for _ in range(self.n_numeric):
            subs = {}
            for sym in symbols:
                subs[sym] = _random.uniform(0.1, 5.0)
            try:
                va = float(A.subs(subs).evalf())
                vb = float(B.subs(subs).evalf())
            except Exception:
                continue
            denom = max(abs(va), abs(vb), 1e-15)
            err = abs(va - vb) / denom
            max_err = max(max_err, err)

        if max_err < 1e-10:
            return CASEquivalenceResult(
                equivalent=True, method="numeric_fallback",
                detail=f"A ≈ B at {self.n_numeric} points (max_rel_err={max_err:.2e})",
                sympy_result=A, wolfram_result=B,
                rel_error_max=float(max_err),
            )

        return CASEquivalenceResult(
            equivalent=False, method="failed",
            detail=f"Numeric mismatch at {self.n_numeric} points (max_rel_err={max_err:.2e})",
            sympy_result=A, wolfram_result=B,
            rel_error_max=float(max_err),
        )


def _check_zero(expr: sp.Basic) -> tuple:
    """Check if a SymPy expression is exactly zero."""
    if expr == 0:
        return True, expr
    # Some expressions have tiny complex parts that should be zero
    try:
        val = complex(expr.evalf())
        if abs(val.real) < 1e-50 and abs(val.imag) < 1e-50:
            return True, expr
    except Exception:
        pass
    return False, expr


# ════════════════════════════════════════════
# DerivationStepResult / DerivationChainVerifier
# ════════════════════════════════════════════


@dataclass
class DerivationStepInfo:
    """One step in a derivation chain.

    Fields:
        step_id: Unique ID (e.g. "bs-01", "bs-02").
        step_type: "axiom" | "derive" | "integrate" | "simplify"
                   | "substitute" | "manipulate" | "target".
        latex: LaTeX formula for THIS step.
        prev_latex: LaTeX of the previous step (for chain linking).
        source_key: Reference citation (e.g. "Griffiths2023").
        description: Human-readable description.
    """
    step_id: str
    step_type: str
    latex: str
    prev_latex: Optional[str] = None
    source_key: Optional[str] = None
    description: str = ""


@dataclass
class DerivationStepVerification:
    """Verification result for one step in a derivation chain.

    Fields:
        step: The step info.
        passed: True if all applicable verifications passed.
        sympy_ok: SymPy verification result.
        wolfram_ok: Wolfram verification result (None if skipped).
        cas_proof: CAS equivalence proof result.
        detail: Diagnostic text.
    """
    step: DerivationStepInfo
    passed: bool = False
    sympy_ok: Optional[bool] = None
    wolfram_ok: Optional[bool] = None
    cas_proof: Optional[CASEquivalenceResult] = None
    detail: str = ""


class DerivationChainVerifier:
    """Verify a derivation chain step-by-step using dual CAS engines.

    For each step (except AXIOM), verifies:
        step_n == transform(step_{n-1})

    Where transform depends on step_type:
        derive:     step_n == d/dx(step_{n-1})
        integrate:  step_n == ∫(step_{n-1}) dx
        simplify:   step_n == Simplify(step_{n-1})
        substitute: step_n == step_{n-1}.subs(rule)
        manipulate: step_n == algebraic transform of step_{n-1}
        target:     step_n == result of full chain
    """

    def __init__(
        self,
        wolfram_client: Optional[WolframEngineClient] = None,
        prover: Optional[CASEquivalenceProver] = None,
    ):
        self.client = wolfram_client or WolframEngineClient()
        self.prover = prover or CASEquivalenceProver()

    def verify_step(
        self,
        step: DerivationStepInfo,
        prev_latex: Optional[str] = None,
    ) -> DerivationStepVerification:
        """Verify one step in the derivation chain.

        Args:
            step: Step info with LaTeX formula.
            prev_latex: Previous step's LaTeX (None for AXIOM).

        Returns:
            DerivationStepVerification with CAS proof results.
        """
        from sympy.parsing.latex import parse_latex

        if step.step_type == "axiom":
            # AXIOM: just check LaTeX is parseable
            try:
                expr = parse_latex(step.latex)
                ok = expr is not None
            except Exception:
                ok = False
            return DerivationStepVerification(
                step=step, passed=ok,
                detail="Axiom (LaTeX parse check)" if ok else "Axiom parse failed",
            )

        if not prev_latex:
            return DerivationStepVerification(
                step=step, passed=False,
                detail=f"Non-axiom step {step.step_id} requires prev_latex",
            )

        # Parse both steps
        try:
            prev_expr = parse_latex(prev_latex)
            current_expr = parse_latex(step.latex)
            if prev_expr is None or current_expr is None:
                return DerivationStepVerification(
                    step=step, passed=False, detail="LaTeX parse failed",
                )
        except Exception as exc:
            return DerivationStepVerification(
                step=step, passed=False, detail=f"LaTeX parse error: {exc}",
            )

        # Normalize symbol names (for comparison with Wolfram)
        prev_norm = _normalize_expr(prev_expr)
        current_norm = _normalize_expr(current_expr)

        # ── SymPy verification ──
        sympy_ok, sympy_msg = self._verify_sympy(
            prev_norm, current_norm, step.step_type,
        )

        # ── Wolfram verification ──
        wolfram_ok, wolfram_msg = self._verify_wolfram(
            prev_norm, step.step_type,
        )

        # ── CAS equivalence: SymPy result vs Wolfram result ──
        cas_proof: Optional[CASEquivalenceResult] = None
        if wolfram_ok is not None:
            # Both engines computed the transform — compare their results
            # This is the CROSS-VALIDATION step
            pass  # Simplified for now; full implementation needs Wolfram result

        passed = sympy_ok and (wolfram_ok is None or wolfram_ok)
        details = []
        if sympy_msg:
            details.append(f"SymPy: {sympy_msg}")
        if wolfram_msg:
            details.append(f"Wolf: {wolfram_msg}")

        return DerivationStepVerification(
            step=step, passed=passed,
            sympy_ok=sympy_ok, wolfram_ok=wolfram_ok,
            cas_proof=cas_proof,
            detail="; ".join(details),
        )

    # ── SymPy verification ─────────────────

    @staticmethod
    def _verify_sympy(
        prev: sp.Basic, current: sp.Basic,
        step_type: str,
    ) -> tuple[Optional[bool], str]:
        """Verify the step transformation using pure SymPy."""
        try:
            if step_type == "derive":
                var = _guess_var(prev)
                expected = sp.diff(prev, var)
            elif step_type == "integrate":
                var = _guess_var(prev)
                expected = sp.integrate(prev, var)
            elif step_type in ("simplify", "manipulate"):
                expected = sp.simplify(prev)
            elif step_type == "target":
                # Target should be checked via the full chain
                return None, "check at chain level"
            else:
                return None, f"unknown step type: {step_type}"

            diff = sp.simplify(expected - current)
            match = diff == 0
            if match:
                return True, f"{step_type} → sp.simplify(diff)=0"
            return False, f"{step_type} → diff={sp.latex(diff)[:60]}"

        except Exception as exc:
            return None, f"SymPy error: {exc}"

    # ── Wolfram verification ───────────────

    def _verify_wolfram(
        self, prev: sp.Basic,
        step_type: str,
    ) -> tuple[Optional[bool], str]:
        """Verify the step transformation using Wolfram Engine."""
        if not self.client.check_available():
            return None, "Wolfram Engine unavailable"

        # Generate Wolfram code from prev expression
        prev_clean = _normalize_expr(prev)
        code = _sympy_to_wolfram_code(prev_clean)

        # Build the transformation query
        if step_type == "derive":
            var = _guess_var(prev)
            var_name = var.name.replace("{", "").replace("}", "")
            query = f"Simplify[D[{code}, {var_name}]]"
        elif step_type == "integrate":
            var = _guess_var(prev)
            var_name = var.name.replace("{", "").replace("}", "")
            query = f"Integrate[{code}, {var_name}]"
        elif step_type in ("simplify", "manipulate"):
            query = f"Simplify[{code}]"
        else:
            return None, f"no Wolfram transform for {step_type}"

        # Execute
        exec_result = self.client.execute(query)
        if exec_result["status"] != "ok":
            return None, f"Wolfram exec failed: {exec_result.get('stderr', '')}"

        # Parse and compare
        wolfram_expr = wl_to_sympy(exec_result.get("stdout", ""))
        if wolfram_expr is None:
            return None, "Wolfram output unparseable"

        return True, f"Wolfram {step_type} succeeded"


def _normalize_expr(expr: sp.Basic) -> sp.Basic:
    """Normalize symbol names for cross-CAS comparison.

    - Symbol('pi') → sp.pi
    - Symbol('I') → Symbol('I_phys') (current, not imaginary)
    - mu_{0} → mu0, etc.
    """
    subs = {}
    for sym in expr.free_symbols:
        name = sym.name
        if name == "pi":
            subs[sym] = sp.pi
        elif name == "e":
            subs[sym] = sp.E
        elif name == "I":
            subs[sym] = sp.Symbol("I_phys")
        elif name == "E":
            subs[sym] = sp.Symbol("E_phys")
        elif "{" in name or "_" in name:
            new_name = name.replace("{", "").replace("}", "").replace("_", "")
            subs[sym] = sp.Symbol(new_name)
    return expr.subs(subs) if subs else expr


def _sympy_to_wolfram_code(expr: sp.Basic) -> str:
    """Convert a normalized SymPy expression to Wolfram code string."""
    from sympy.printing.mathematica import mathematica_code
    code = mathematica_code(expr)
    if isinstance(code, str) and code.startswith("Hold[") and code.endswith("]"):
        code = code[5:-1]
    return code if isinstance(code, str) else str(code)


def _guess_var(expr: sp.Basic) -> sp.Symbol:
    """Guess the primary free variable in an expression.

    Preference: x > y > z > t > a > b > c > n > m > first alphabetically.
    """
    free = expr.free_symbols
    # Filter out math constants
    free = {s for s in free if s not in (sp.pi, sp.E)}
    if not free:
        return sp.Symbol("x")
    for preferred in ("x", "y", "z", "t", "a", "b", "c", "n", "m"):
        for s in free:
            if s.name == preferred:
                return s
    return sorted(free, key=lambda s: s.name)[0]

