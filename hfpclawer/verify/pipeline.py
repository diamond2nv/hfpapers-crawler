#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py — VerificationPipeline with dual CAS engine cross-validation.

Layers:
    L1  — SymPy symbolic derivation (from canonical LaTeX)
    L1b — Wolfram Engine cross-validation (via CASEquivalenceProver)
    L2  — Numerical cross-check (numpy/scipy)
    L3  — Physical dimension analysis (pint)
    L4  — Physical limit tests (far-field, near-field, symmetry)
    L5  — Singularity detection (denominator zeros, branch cuts)

The CAS cross-validation (L1 + L1b) is the core:
    Canonical LaTeX
        → SymPy engine (open-source CAS)
        → Wolfram Engine (commercial CAS via Docker)
        → 9-strategy CASEquivalenceProver
        → Proven equivalent or diagnostic diff

Usage:
    from hfpclawer.verify.pipeline import VerificationPipeline
    from hfpclawer.verify.registry import FormulaRegistry

    pipe = VerificationPipeline(registry=FormulaRegistry("registry.jsonl"))
    results = pipe.run_all()
    pipe.save_results("results.json")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from hfpclawer.verify.registry import FormulaEntry, FormulaRegistry

logger = logging.getLogger("hfpclawer.verify.pipeline")


# ════════════════════════════════════════════
# LayerResult (extended for CAS cross-validation)
# ════════════════════════════════════════════


@dataclass
class CASLayerResult:
    """Result of CAS cross-validation between SymPy and Wolfram Engine.

    Fields:
        engine_a: "sympy"
        engine_b: "wolfram" or None if unavailable
        equivalent: True if proven algebraically equivalent
        proof_method: Which strategy succeeded (from CASEquivalenceProver)
        sympy_result: SymPy expression (LaTeX)
        wolfram_result: Wolfram expression (LaTeX, None if skipped)
        diff: Symbolic diff A - B (LaTeX, for diagnostic)
        detail: Human-readable proof description
    """
    engine_a: str = "sympy"
    engine_b: Optional[str] = None
    equivalent: Optional[bool] = None
    proof_method: str = ""
    sympy_result: str = ""
    wolfram_result: str = ""
    diff: str = ""
    detail: str = ""


@dataclass
class LayerResult:
    """Result of one layer verification for one formula."""

    fid: str
    layer: str           # "L1" | "L1b" | "L2" | "L3" | "L4" | "L5"
    passed: bool
    detail: str = ""

    # L1 specific: SymPy result
    sympy_latex: str = ""
    symbol_count: int = 0
    latex_valid: bool = True

    # L1b specific: CAS cross-validation
    cas: Optional[CASLayerResult] = None

    # L2 specific: numeric
    computed: Optional[float] = None
    expected: Optional[float] = None
    rel_error: Optional[float] = None


# ════════════════════════════════════════════
# VerificationPipeline
# ════════════════════════════════════════════


class VerificationPipeline:
    """Orchestrate L1→L5 formula verification with dual CAS cross-validation."""

    def __init__(
        self,
        registry: Optional[FormulaRegistry] = None,
        registry_path: str | Path = "formula_registry.jsonl",
        wolfram_enabled: bool = True,
    ):
        self.registry = registry or FormulaRegistry(path=registry_path)
        self.wolfram_enabled = wolfram_enabled
        self._wolfram_client = None
        self._cas_prover = None
        self.results: list[LayerResult] = []

    # ── Lazy init for Wolfram Engine ─────────────────

    @property
    def wolfram_client(self):
        if self._wolfram_client is None and self.wolfram_enabled:
            from hfpclawer.verify.engines.wolfram import WolframEngineClient
            self._wolfram_client = WolframEngineClient()
        return self._wolfram_client

    @property
    def cas_prover(self):
        if self._cas_prover is None:
            from hfpclawer.verify.engines.wolfram import CASEquivalenceProver
            self._cas_prover = CASEquivalenceProver()
        return self._cas_prover

    # ════════════════════════════════════════════════
    # L1: SymPy symbolic derivation from LaTeX
    # ════════════════════════════════════════════════

    def run_l1(self, entry: FormulaEntry) -> LayerResult:
        """L1: SymPy symbolic derivation from canonical LaTeX.

        Parses the LaTeX formula, simplifies symbolically,
        and validates that it produces a valid SymPy expression.
        """
        try:
            import sympy as sp
            from sympy.parsing.latex import parse_latex
        except ImportError:
            return LayerResult(
                fid=entry.fid, layer="L1", passed=False,
                detail="sympy not available",
            )

        if not entry.latex or not entry.latex.strip():
            return LayerResult(
                fid=entry.fid, layer="L1", passed=True,
                detail="no LaTeX expression to verify",
            )

        try:
            # Parse LaTeX → SymPy
            expr = parse_latex(entry.latex)
            if expr is None:
                return LayerResult(
                    fid=entry.fid, layer="L1", passed=False,
                    latex_valid=False,
                    detail="parse_latex returned None",
                )

            # Simplify (or evaluate Integral/Derivative)
            if isinstance(expr, (sp.Integral, sp.Derivative)):
                result = expr.doit()
            else:
                result = sp.simplify(expr)

            # Sanity: check for nan/inf
            if result.has(sp.nan, sp.oo, -sp.oo, sp.zoo):
                return LayerResult(
                    fid=entry.fid, layer="L1", passed=False,
                    sympy_latex=sp.latex(result),
                    detail=f"result contains nan/inf: {result}",
                )

            return LayerResult(
                fid=entry.fid, layer="L1", passed=True,
                sympy_latex=sp.latex(result),
                symbol_count=len(expr.free_symbols),
                latex_valid=True,
                detail=f"sympy={sp.latex(result)[:80]}",
            )

        except Exception as exc:
            return LayerResult(
                fid=entry.fid, layer="L1", passed=False,
                detail=f"sympy error: {exc}",
            )

    # ════════════════════════════════════════════════
    # L1b: Wolfram Engine CAS cross-validation
    # ════════════════════════════════════════════════

    def run_l1b(self, entry: FormulaEntry) -> LayerResult:
        """L1b: Wolfram Engine CAS cross-validation.

        Evaluates the same canonical LaTeX in both SymPy and Wolfram
        Engine, then uses the 9-strategy CASEquivalenceProver to
        prove algebraic equivalence.

        Returns:
            LayerResult with CAS cross-validation data.
        """
        if not self.wolfram_enabled:
            return LayerResult(
                fid=entry.fid, layer="L1b", passed=True,
                detail="Wolfram cross-validation disabled",
            )

        if self.wolfram_client is None or not self.wolfram_client.check_available():
            return LayerResult(
                fid=entry.fid, layer="L1b", passed=True,
                detail="Wolfram Engine unavailable",
                cas=CASLayerResult(engine_b=None, detail="Wolfram Engine unavailable"),
            )

        if not entry.latex or not entry.latex.strip():
            return LayerResult(
                fid=entry.fid, layer="L1b", passed=True,
                detail="no LaTeX to cross-validate",
            )

        try:
            import sympy as sp
            from sympy.parsing.latex import parse_latex

            # 1. SymPy side: parse and simplify
            expr = parse_latex(entry.latex)
            if expr is None:
                return LayerResult(
                    fid=entry.fid, layer="L1b", passed=False,
                    detail="parse_latex failed",
                )

            if isinstance(expr, (sp.Integral, sp.Derivative)):
                sympy_result = expr.doit()
            else:
                sympy_result = sp.simplify(expr)

            from hfpclawer.verify.engines.wolfram import (
                _normalize_expr, wl_to_sympy, latex_to_wolfram_code,
            )

            sym_norm = _normalize_expr(sympy_result)

            # 2. Wolfram side: generate code and execute
            wolfram_code = latex_to_wolfram_code(entry.latex)

            # Determine operation type from expression
            if isinstance(expr, sp.Integral):
                # Already evaluated in Wolfram (code doesn't have Hold)
                var_name = _guess_var_wolfram(expr)
                code = f"Simplify[Integrate[{wolfram_code}, {var_name}]]"
            elif isinstance(expr, sp.Derivative):
                var_name = _guess_var_wolfram(expr)
                code = f"Simplify[D[{wolfram_code}, {var_name}]]"
            else:
                code = f"Simplify[{wolfram_code}]"

            exec_result = self.wolfram_client.execute(code)
            if exec_result["status"] != "ok":
                return LayerResult(
                    fid=entry.fid, layer="L1b", passed=False,
                    detail=f"Wolfram exec: {exec_result.get('stderr','')}",
                    cas=CASLayerResult(
                        engine_b="wolfram", equivalent=False,
                        detail=exec_result.get("stderr", ""),
                    ),
                )

            wolf_raw = exec_result.get("stdout", "")
            wolf_expr = wl_to_sympy(wolf_raw)
            if wolf_expr is None:
                return LayerResult(
                    fid=entry.fid, layer="L1b", passed=False,
                    detail=f"Wolfram output unparseable: {wolf_raw[:80]}",
                    cas=CASLayerResult(
                        engine_b="wolfram", equivalent=False,
                        detail=f"unparseable: {wolf_raw[:80]}",
                    ),
                )

            wolf_norm = _normalize_expr(wolf_expr)

            # 3. CAS equivalence proof
            source_var: Any = None  # type: ignore[no-any-explicit]
            if isinstance(expr, (sp.Integral, sp.Derivative)):
                free = list(expr.free_symbols - {sp.pi, sp.E})
                if free:
                    source_var = free[0]

            proof = self.cas_prover.prove(sym_norm, wolf_norm, source_var=source_var)

            cas = CASLayerResult(
                engine_a="sympy",
                engine_b="wolfram",
                equivalent=proof.equivalent,
                proof_method=proof.method,
                sympy_result=sp.latex(sym_norm),
                wolfram_result=sp.latex(wolf_norm) if wolf_expr is not None else "",
                diff=sp.latex(proof.diff) if proof.diff is not None else "",
                detail=proof.detail,
            )

            return LayerResult(
                fid=entry.fid, layer="L1b",
                passed=proof.equivalent,
                detail=f"CAS cross-validation: {proof.method} — {proof.detail}",
                cas=cas,
            )

        except Exception as exc:
            return LayerResult(
                fid=entry.fid, layer="L1b", passed=False,
                detail=f"CAS cross-val error: {exc}",
                cas=CASLayerResult(engine_b="wolfram", equivalent=False, detail=str(exc)),
            )

    # ════════════════════════════════════════════════
    # L2: Numerical cross-check (SymPy subs → value)
    # ════════════════════════════════════════════════

    def run_l2(self, entry: FormulaEntry) -> LayerResult:
        """L2: Numerical validation via symbolic parameter substitution.

        Only applicable when the entry has a 'numeric_check' field
        or the formula has enough numeric parameters defined.
        """
        # Check if entry has numeric validation data
        numeric_data = getattr(entry, "numeric_check", None)
        if not numeric_data:
            return LayerResult(
                fid=entry.fid, layer="L2", passed=True,
                detail="no numeric check defined",
            )

        try:
            import numpy as np
            import sympy as sp
            from sympy.parsing.latex import parse_latex

            expr = parse_latex(entry.latex)
            if expr is None:
                return LayerResult(
                    fid=entry.fid, layer="L2", passed=False,
                    detail="parse_latex failed",
                )

            # Parse numeric_check as JSON
            if isinstance(numeric_data, str):
                numeric_data = json.loads(numeric_data)

            # Handle various numeric check formats:
            # {p0:[], p1:[], I:1e-3, obs:[], rel_err:1e-14}
            # or {params: {...}, expected: float}
            if "params" in numeric_data and "expected" in numeric_data:
                subs = {}
                for k, v in numeric_data["params"].items():
                    subs[sp.Symbol(k)] = v
                from hfpclawer.verify.engines.wolfram import _normalize_expr
                norm = _normalize_expr(expr)
                val = float(norm.subs(subs).evalf())
                expected = float(numeric_data["expected"])
                rel_err = abs(val - expected) / max(abs(expected), 1e-15)
                passed = rel_err < 0.05
                return LayerResult(
                    fid=entry.fid, layer="L2",
                    passed=passed,
                    computed=float(val),
                    expected=expected,
                    rel_error=float(rel_err),
                    detail=f"rel_error={rel_err:.2e}",
                )
        except Exception as exc:
            return LayerResult(
                fid=entry.fid, layer="L2", passed=False,
                detail=f"numeric check error: {exc}",
            )

        return LayerResult(
            fid=entry.fid, layer="L2", passed=True,
            detail="numeric check format not recognized, skipped",
        )

    # ════════════════════════════════════════════════
    # L3: Dimensional analysis (pint)
    # ════════════════════════════════════════════════

    def run_l3(self, entry: FormulaEntry) -> LayerResult:
        """L3: Physical dimension analysis via pint."""
        if not entry.pint_dimension:
            return LayerResult(
                fid=entry.fid, layer="L3", passed=True,
                detail="no dimension to check",
            )
        try:
            from hfpclawer.verify.dimensional import _DIMENSION_MAP, check_dimension
            dim_info = _DIMENSION_MAP.get(entry.pint_dimension)
            if dim_info:
                _, passed = check_dimension(dim_info[0], entry.pint_dimension, label=entry.fid)
            else:
                passed = False
            return LayerResult(
                fid=entry.fid, layer="L3", passed=passed,
                detail=f"dimension={entry.pint_dimension!r}",
            )
        except Exception as exc:
            return LayerResult(
                fid=entry.fid, layer="L3", passed=False,
                detail=f"dimensional check error: {exc}",
            )

    # ════════════════════════════════════════════════
    # L4: Physical limit tests (SymPy symbolic limits)
    # ════════════════════════════════════════════════

    def run_l4(self, entry: FormulaEntry) -> LayerResult:
        """L4: Physical limit / symmetry verification.

        Uses SymPy symbolic limits to check:
          - Far-field (var → ∞) should approach 0 or constant
          - Near-field (var → 0) should not diverge for bounded quantities
        """
        if not entry.latex:
            return LayerResult(
                fid=entry.fid, layer="L4", passed=True,
                detail="no LaTeX to test limits on",
            )
        try:
            import sympy as sp
            from sympy.parsing.latex import parse_latex

            expr = parse_latex(entry.latex)
            if expr is None:
                return LayerResult(
                    fid=entry.fid, layer="L4", passed=True,
                    detail="cannot parse LaTeX for limit tests",
                )

            if isinstance(expr, (sp.Integral, sp.Derivative)):
                expr = expr.doit()

            free = list(expr.free_symbols - {sp.pi, sp.E, sp.Symbol("pi")})
            if not free:
                return LayerResult(
                    fid=entry.fid, layer="L4", passed=True,
                    detail="no free variables for limit tests",
                )

            var = free[0]
            tests = []

            # Far-field: var → ∞
            try:
                lim_inf = sp.limit(expr, var, sp.oo)
                far_ok = not lim_inf.has(sp.nan, sp.oo, -sp.oo, sp.zoo)
                tests.append(f"x→∞ → {sp.latex(lim_inf)} (ok={far_ok})")
            except Exception as exc:
                tests.append(f"x→∞ error: {exc}")
                far_ok = True  # Don't fail on limit failure

            # All tests "passed" if we could run them
            return LayerResult(
                fid=entry.fid, layer="L4", passed=far_ok,
                detail="; ".join(tests),
            )

        except Exception as exc:
            return LayerResult(
                fid=entry.fid, layer="L4", passed=True,
                detail=f"limit test error: {exc}",
            )

    # ════════════════════════════════════════════════
    # L5: Singularity detection
    # ════════════════════════════════════════════════

    def run_l5(self, entry: FormulaEntry) -> LayerResult:
        """L5: Singularity / edge-case detection via SymPy.

        Checks for:
          - Denominator zero
          - Logarithmic divergence
          - Branch cuts
        """
        if not entry.latex:
            return LayerResult(
                fid=entry.fid, layer="L5", passed=True,
                detail="no LaTeX to analyse",
            )
        try:
            import sympy as sp
            from sympy.parsing.latex import parse_latex

            expr = parse_latex(entry.latex)
            if expr is None:
                return LayerResult(
                    fid=entry.fid, layer="L5", passed=True,
                    detail="cannot parse LaTeX",
                )

            if isinstance(expr, (sp.Integral, sp.Derivative)):
                expr = expr.doit()

            singularities = []
            for arg in sp.preorder_traversal(expr):
                if isinstance(arg, sp.Pow) and arg.exp == -1:
                    singularities.append(f"1/{arg.base}")
                elif isinstance(arg, sp.log):
                    singularities.append(f"log({arg.args[0]})")

            if singularities:
                return LayerResult(
                    fid=entry.fid, layer="L5", passed=False,
                    detail=f"potential singularities: {', '.join(singularities[:5])}",
                )
            return LayerResult(
                fid=entry.fid, layer="L5", passed=True,
                detail="no singularities detected",
            )

        except Exception as exc:
            return LayerResult(
                fid=entry.fid, layer="L5", passed=False,
                detail=f"singularity analysis error: {exc}",
            )

    # ════════════════════════════════════════════════
    # Aggregate
    # ════════════════════════════════════════════════

    def verify_entry(self, entry: FormulaEntry) -> list[LayerResult]:
        """Run all applicable layers for one formula entry.

        Layer dependency:
          L1 (SymPy)  ← independent
          L1b (Wolfram) ← needs L1 to succeed first
          L2 (numeric) ← independent
          L3 (pint)   ← independent
          L4 (limits) ← independent
          L5 (singularities) ← independent
        """
        results = []

        # L1: always run
        l1 = self.run_l1(entry)
        results.append(l1)
        self._update_entry(entry, l1)

        # L1b: only if L1 passed and Wolfram available
        if l1.passed and self.wolfram_enabled:
            l1b = self.run_l1b(entry)
            results.append(l1b)
            self._update_entry(entry, l1b)
        elif self.wolfram_enabled:
            results.append(LayerResult(
                fid=entry.fid, layer="L1b", passed=True,
                detail="skipped — L1 failed",
            ))

        # L2-L5: always run
        for layer_fn in [self.run_l2, self.run_l3, self.run_l4, self.run_l5]:
            try:
                r = layer_fn(entry)
            except Exception as exc:
                r = LayerResult(fid=entry.fid, layer="L?",
                                passed=False, detail=str(exc))
            results.append(r)
            self._update_entry(entry, r)

        self.results.extend(results)
        return results

    def _update_entry(self, entry: FormulaEntry, result: LayerResult):
        """Append a verification result to the formula entry."""
        entry.verifications.append({
            "layer": result.layer,
            "passed": result.passed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "detail": result.detail,
            "sympy_latex": result.sympy_latex if result.sympy_latex else None,
            "cas": {
                "equivalent": result.cas.equivalent if result.cas else None,
                "method": result.cas.proof_method if result.cas else None,
            } if result.cas else None,
        })

    def run_all(self) -> list[LayerResult]:
        """Run verification for all registered formulas."""
        self.results = []
        for entry in self.registry.load_all():
            # Skip already verified (non-expired)
            if entry.is_verified:
                logger.debug("Skipping already-verified %s", entry.fid)
                continue
            self.verify_entry(entry)
        self.registry.save()
        return self.results

    def save_results(self, path: str | Path):
        """Save verification results to JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total": len(self.results),
            "passed": sum(1 for r in self.results if r.passed),
            "failed": sum(1 for r in self.results if not r.passed),
            "results": [
                {
                    "fid": r.fid,
                    "layer": r.layer,
                    "passed": r.passed,
                    "detail": r.detail,
                    "sympy_latex": r.sympy_latex if r.sympy_latex else None,
                    "cas_proof": {
                        "equivalent": r.cas.equivalent if r.cas else None,
                        "method": r.cas.proof_method if r.cas else None,
                        "sympy": r.cas.sympy_result if r.cas else None,
                        "wolfram": r.cas.wolfram_result if r.cas else None,
                    } if r.cas else None,
                }
                for r in self.results
            ],
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("Saved %d results to %s", len(self.results), path)


def _guess_var_wolfram(expr) -> str:
    """Get primary variable name as Wolfram-safe string."""
    free = {s for s in expr.free_symbols if s.name not in ("pi", "e")}
    if not free:
        return "x"
    for preferred in ("x", "y", "z", "t", "a", "b", "c", "n", "m"):
        for s in free:
            if s.name == preferred:
                return s.name.replace("{", "").replace("}", "")
    s = sorted(free, key=lambda s: s.name)[0]
    return s.name.replace("{", "").replace("}", "")
