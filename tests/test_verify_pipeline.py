#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end test: FormulaRegistry → VerificationPipeline → Wolfram CAS cross-val."""

import tempfile
from pathlib import Path

import pytest
from sympy.parsing.latex import parse_latex

from hfpclawer.verify.engines.wolfram import _normalize_expr, wl_to_sympy
from hfpclawer.verify.pipeline import VerificationPipeline
from hfpclawer.verify.registry import FormulaEntry, FormulaRegistry


@pytest.fixture
def temp_registry():
    """Create a temp FormulaRegistry with test formulas."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test_registry.jsonl"
        reg = FormulaRegistry(path=path)

        # Add formulas commonly found in physics literature
        entries = [
            FormulaEntry(
                fid="eq:trig-identity",
                latex=r"\sin^2 x + \cos^2 x",
                pint_dimension="dimensionless",
                source_keys=["Griffiths2023"],
                tags=["trigonometry"],
            ),
            FormulaEntry(
                fid="eq:tan-identity",
                latex=r"\frac{\sin x}{\cos x}",
                sympy="sin(x)/cos(x)",
                pint_dimension="dimensionless",
                source_keys=["Griffiths2023"],
                tags=["trigonometry"],
            ),
        ]
        for entry in entries:
            reg.add(entry)
        reg.save()
        yield reg


class TestPipelineCASCrossValidation:
    """Test the VerificationPipeline with CAS cross-validation."""

    def test_l1_latex_parsing(self, temp_registry):
        """L1 should parse LaTeX and produce SymPy result."""
        pipe = VerificationPipeline(registry=temp_registry, wolfram_enabled=False)
        entry = temp_registry.get("eq:trig-identity")
        result = pipe.run_l1(entry)
        assert result.passed, f"L1 failed: {result.detail}"
        assert "1" in result.sympy_latex  # sin²x+cos²x simplifies to 1

    def test_l1b_wolfram_cross_validation(self, temp_registry):
        """L1b should cross-validate with Wolfram Engine."""
        from hfpclawer.verify.engines.wolfram import WolframEngineClient
        client = WolframEngineClient(timeout=15)
        if not client.check_available():
            pytest.skip("Wolfram Engine container not available")

        pipe = VerificationPipeline(registry=temp_registry, wolfram_enabled=True)
        entry = temp_registry.get("eq:trig-identity")

        # Run L1 first
        l1 = pipe.run_l1(entry)
        assert l1.passed

        # Run L1b
        result = pipe.run_l1b(entry)
        assert result.passed, f"L1b failed: {result.detail}"
        assert result.cas is not None
        assert result.cas.equivalent == True, f"CAS not equivalent: {result.detail}"

    def test_l1b_trig_identity(self, temp_registry):
        """Wolfram should confirm sin²x+cos²x = 1."""
        from hfpclawer.verify.engines.wolfram import WolframEngineClient
        client = WolframEngineClient(timeout=15)
        if not client.check_available():
            pytest.skip("Wolfram Engine not available")

        pipe = VerificationPipeline(registry=temp_registry, wolfram_enabled=True)
        entry = temp_registry.get("eq:trig-identity")
        results = pipe.verify_entry(entry)

        # Check L1b result has CAS proof
        l1b_results = [r for r in results if r.layer == "L1b"]
        assert len(l1b_results) == 1
        r = l1b_results[0]
        assert r.passed
        assert r.cas is not None
        assert r.cas.equivalent == True
        assert r.cas.proof_method in ("simplify", "expand", "trigsimp")

    def test_layer_independence(self, temp_registry):
        """L3/L4/L5 should run independently of L1b."""
        pipe = VerificationPipeline(registry=temp_registry, wolfram_enabled=False)
        entry = temp_registry.get("eq:trig-identity")

        l3 = pipe.run_l3(entry)
        assert l3.passed  # dimensionless

        l5 = pipe.run_l5(entry)
        assert l5.passed  # no singularities

    def test_wl_to_sympy_integration(self):
        """Full roundtrip: LaTeX → SymPy → Wolfram → SymPy → compare."""
        from hfpclawer.verify.engines.wolfram import (
            WolframEngineClient,
            latex_to_wolfram_code,
        )
        client = WolframEngineClient(timeout=15)
        if not client.check_available():
            pytest.skip("Wolfram Engine not available")

        latex = r"\sin^2 x + \cos^2 x"
        code = latex_to_wolfram_code(latex)

        exec_result = client.execute(f"Simplify[{code}]")
        assert exec_result["status"] == "ok"

        wolf_raw = exec_result.get("stdout", "")
        wolf_sympy = wl_to_sympy(wolf_raw)

        sympy_expr = parse_latex(latex)
        import sympy as sp
        sympy_simplified = sp.simplify(sympy_expr)

        diff = sp.simplify(sympy_simplified - _normalize_expr(wolf_sympy))
        assert diff == 0, f"Expressions not equivalent: {diff}"

    def test_numeric_check(self, temp_registry):
        """L2 should handle formulas gracefully without numeric_check."""
        reg = temp_registry
        entry = FormulaEntry(
            fid="eq:biot-savart-test",
            latex=r"\frac{\mu_0 I}{2\pi d}",
            pint_dimension="magnetic flux density",
            source_keys=["Test"],
        )
        reg.add(entry)
        reg.save()

        pipe = VerificationPipeline(registry=reg, wolfram_enabled=False)
        result = pipe.run_l2(entry)
        # Without numeric data, L2 should skip gracefully
        assert result.passed
        assert "no numeric check defined" in result.detail
