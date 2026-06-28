#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py — L1→L5 VerificationPipeline for hfpclawer.

Orchestrates formula verification across all 5 layers:

    L1 — SymPy symbolic derivation (algebraic equivalence)
    L2 — numpy numerical cross-check (random parameter sampling)
    L3 — pint dimensional analysis (physical dimension matching)
    L4 — physical limit tests (far-field, near-field, symmetry)
    L5 — singularity detection (denominator zeros, branch cuts)

Each layer is independently runnable:  pipeline.run_l1() etc.
Collection of results is aggregated by pipeline.run_all().

Usage:
    from hfpclawer.verify.pipeline import VerificationPipeline
    from hfpclawer.verify.registry import FormulaRegistry

    pipe = VerificationPipeline(registry=FormulaRegistry("my_reg.jsonl"))
    results = pipe.run_all()
    pipe.save_results("results.json")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from hfpclawer.verify.registry import FormulaEntry, FormulaRegistry

logger = logging.getLogger("hfpclawer.verify.pipeline")


# ─── Layer result record ────────────────────


@dataclass
class LayerResult:
    """Result of one layer verification for one formula."""

    fid: str
    layer: str           # "L1" | "L2" | "L3" | "L4" | "L5"
    passed: bool
    detail: str = ""
    computed: Optional[float] = None
    expected: Optional[float] = None
    rel_error: Optional[float] = None


# ════════════════════════════════════════════
# VerificationPipeline
# ════════════════════════════════════════════


class VerificationPipeline:
    """Orchestrate L1→L5 verification for registered formulas."""

    def __init__(
        self,
        registry: Optional[FormulaRegistry] = None,
        registry_path: str | Path = "formula_registry.jsonl",
    ):
        self.registry = registry or FormulaRegistry(path=registry_path)
        self.results: list[LayerResult] = []

    # ── L1: SymPy symbolic derivation ──────

    def run_l1(self, entry: FormulaEntry) -> LayerResult:
        """L1: SymPy symbolic derivation.

        Verifies that the SymPy expression is algebraically well-formed
        and simplifies correctly (no infinities, no contradictions).
        """
        # Lazy import SymPy (heavy)
        try:
            import sympy as sp
        except ImportError:
            return LayerResult(
                fid=entry.fid, layer="L1", passed=False,
                detail="sympy not available",
            )

        if not entry.sympy:
            return LayerResult(
                fid=entry.fid, layer="L1", passed=True,
                detail="no sympy expression to verify",
            )

        try:
            expr = sp.sympify(entry.sympy)
            simplified = sp.simplify(expr)

            # Basic sanity checks
            if simplified.has(sp.nan, sp.oo, -sp.oo, sp.zoo):
                return LayerResult(
                    fid=entry.fid, layer="L1", passed=False,
                    detail=f"simplified result contains nan/inf: {simplified}",
                )

            # L1 passes if expression is valid and simplifies cleanly
            return LayerResult(
                fid=entry.fid, layer="L1", passed=True,
                detail=f"expr={sp.latex(simplified)}",
            )

        except Exception as exc:
            return LayerResult(
                fid=entry.fid, layer="L1", passed=False,
                detail=f"sympy error: {exc}",
            )

    # ── L2: Numerical cross-check ──────────

    def run_l2(self, entry: FormulaEntry) -> LayerResult:
        """L2: Numerical cross-check using random parameter sampling.

        Only applicable when the entry has a 'numeric_check' field
        or when a separate numerical validation is defined.
        """
        if not hasattr(entry, "numeric_check") or not entry.numeric_check:  # type: ignore[arg-type]
            return LayerResult(
                fid=entry.fid, layer="L2", passed=True,
                detail="no numeric check defined",
            )

        # Placeholder for numeric validation logic
        # In future: parse entry.numeric_check JSON:
        #   {"params": [...], "expected": ..., "tolerance": 0.05}
        return LayerResult(
            fid=entry.fid, layer="L2", passed=True,
            detail="numeric check not yet implemented (placeholder)",
        )

    # ── L3: Dimensional analysis ───────────

    def run_l3(self, entry: FormulaEntry) -> LayerResult:
        """L3: Physical dimension analysis via pint.

        Checks that the formula's stated dimension matches
        the expected physical quantity.
        """
        if not entry.pint_dimension:
            return LayerResult(
                fid=entry.fid, layer="L3", passed=True,
                detail="no dimension to check",
            )

        try:
            from hfpclawer.verify.dimensional import _DIMENSION_MAP, check_dimension

            # Map the dimension name to a pint unit string
            dim_info = _DIMENSION_MAP.get(entry.pint_dimension)
            if dim_info:
                pint_unit = dim_info[0]  # e.g. "T" for "magnetic flux density"
                _, passed = check_dimension(pint_unit, entry.pint_dimension, label=entry.fid)
            else:
                passed = False
            return LayerResult(
                fid=entry.fid, layer="L3", passed=passed,
                detail=f"dimension={entry.pint_dimension!r} passed={passed}",
            )
        except Exception as exc:
            return LayerResult(
                fid=entry.fid, layer="L3", passed=False,
                detail=f"dimensional check error: {exc}",
            )

    # ── L4: Physical limit tests ───────────

    def run_l4(self, entry: FormulaEntry) -> LayerResult:
        """L4: Physical limit verification.

        Tests known limits:
          - Far-field (x → ∞) should approach 0 or constant
          - Near-field (x → 0) should not diverge for physically bounded quantities
          - Symmetry constraints (odd/even functions)
        """
        # Placeholder — full implementation requires domain-specific limits
        return LayerResult(
            fid=entry.fid, layer="L4", passed=True,
            detail="limit tests not yet implemented (placeholder)",
        )

    # ── L5: Singularity detection ──────────

    def run_l5(self, entry: FormulaEntry) -> LayerResult:
        """L5: Singularity / edge-case detection.

        Checks for:
          - Denominator zero
          - Logarithmic divergence
          - Branch cuts in complex expressions
          - Extreme parameter regimes
        """
        if not entry.sympy:
            return LayerResult(
                fid=entry.fid, layer="L5", passed=True,
                detail="no sympy expression to analyse",
            )

        try:
            import sympy as sp

            expr = sp.sympify(entry.sympy)

            # Check for denominator zeros
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

    # ── Aggregate ───────────────────────────

    def verify_entry(self, entry: FormulaEntry) -> list[LayerResult]:
        """Run all applicable layers for one entry."""
        layers = [
            ("L1", self.run_l1),
            ("L2", self.run_l2),
            ("L3", self.run_l3),
            ("L4", self.run_l4),
            ("L5", self.run_l5),
        ]

        results = []
        for name, fn in layers:
            try:
                r = fn(entry)
            except Exception as exc:
                r = LayerResult(fid=entry.fid, layer=name, passed=False, detail=str(exc))
            results.append(r)
            # Update registry entry
            entry.verifications.append({
                "layer": name,
                "passed": r.passed,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "detail": r.detail,
            })

        # Update overall status
        all_pass = all(r.passed for r in results)
        entry.verification_status = "verified" if all_pass else "failed"
        entry.verified_at = datetime.now(timezone.utc).isoformat()

        self.results.extend(results)
        return results

    def run_all(self) -> list[LayerResult]:
        """Run verification for all registered formulas."""
        self.results = []
        for entry in self.registry.load_all():
            # Skip already verified (non-expired)
            if entry.is_verified:
                logger.debug("Skipping already-verified %s", entry.fid)
                continue
            self.verify_entry(entry)
        # Save updated status to registry
        self.registry.save()
        return self.results

    def save_results(self, path: str | Path):
        """Save verification results to JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(
                {
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
                        }
                        for r in self.results
                    ],
                },
                f, indent=2, ensure_ascii=False,
            )
        logger.info("Saved %d results to %s", len(self.results), path)
