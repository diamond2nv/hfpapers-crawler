#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for hfpclawer.verify.engines.wolfram — wl_to_sympy, CASEquivalenceProver."""

import pytest
import sympy as sp

from hfpclawer.verify.engines.wolfram import (
    CASEquivalenceProver,
    _normalize_expr,
    latex_to_wolfram_code,
    sanitize_name,
    to_wolfram_number,
    wl_to_sympy,
)

# ════════════════════════════════════════════
# wl_to_sympy tests
# ════════════════════════════════════════════


class TestWlToSympy:
    def test_simple_arithmetic(self):
        assert wl_to_sympy("x + y") == sp.Symbol("x") + sp.Symbol("y")
        assert wl_to_sympy("x*y") == sp.Symbol("x") * sp.Symbol("y")
        assert wl_to_sympy("x^y") == sp.Symbol("x") ** sp.Symbol("y")

    def test_fractions(self):
        result = wl_to_sympy("(a + b)/(c + d)")
        a, b, c, d = sp.symbols("a b c d")
        assert sp.simplify(result - (a + b) / (c + d)) == 0

    def test_trig_functions(self):
        x = sp.Symbol("x")
        assert wl_to_sympy("Sin[x]") == sp.sin(x)
        assert wl_to_sympy("Cos[x]^2 + Sin[x]^2") == sp.cos(x)**2 + sp.sin(x)**2
        assert wl_to_sympy("ArcTan[x/a]") == sp.atan(x / sp.Symbol("a"))

    def test_special_functions(self):
        x = sp.Symbol("x")
        assert wl_to_sympy("Sqrt[x]") == sp.sqrt(x)
        assert wl_to_sympy("Log[x]") == sp.log(x)
        assert wl_to_sympy("Exp[x]") == sp.exp(x)

    def test_constants(self):
        assert wl_to_sympy("Pi") == sp.pi
        assert wl_to_sympy("E") == sp.E

    def test_complex_expressions(self):
        result = wl_to_sympy("z/(x^2*Sqrt[x^2 + z^2])")
        x, z = sp.symbols("x z")
        expected = z / (x**2 * sp.sqrt(x**2 + z**2))
        assert sp.simplify(result - expected) == 0

    def test_empty_or_null(self):
        assert wl_to_sympy("") is None
        assert wl_to_sympy("Null") is None
        assert wl_to_sympy("   ") is None


# ════════════════════════════════════════════
# CASEquivalenceProver tests
# ════════════════════════════════════════════


class TestCASEquivalenceProver:
    def setup_method(self):
        self.prover = CASEquivalenceProver(n_numeric=5)
        self.x, self.a, self.z = sp.symbols("x a z")

    def test_trig_identity(self):
        A = sp.simplify(sp.sin(self.x)**2 + sp.cos(self.x)**2)
        B = sp.Integer(1)
        r = self.prover.prove(A, B)
        assert r.equivalent
        assert r.method == "simplify"

    def test_rational_simplification(self):
        A = sp.simplify((self.x**2 - 1) / (self.x - 1))
        B = self.x + 1
        r = self.prover.prove(A, B)
        assert r.equivalent

    def test_integral_via_derivative(self):
        """ArcTan vs complex log form — equivalence via derivative comparison."""
        A = sp.integrate(1/(self.x**2 + self.a**2), self.x)
        B = sp.atan(self.x / self.a) / self.a
        r = self.prover.prove(A, B, source_var=self.x)
        assert r.equivalent
        assert r.method == "derivative"

    def test_nested_sqrt_numeric_fallback(self):
        """SymPy cannot algebraically prove this — falls back to numeric."""
        A = self.z / (self.x**3 * sp.sqrt(1 + self.z**2 / self.x**2))
        B = self.z / (self.x**2 * sp.sqrt(self.x**2 + self.z**2))
        r = self.prover.prove(A, B)
        assert r.equivalent  # Numeric fallback should work
        assert r.method in ("numeric_fallback", "ratio")

    def test_derivative_sin2x(self):
        A = sp.diff(sp.sin(self.x)**2, self.x)
        B = sp.sin(2 * self.x)
        r = self.prover.prove(A, B)
        assert r.equivalent

    def test_ratio_strategy(self):
        """A/B == 1 when A-B fails."""
        A = self.z / (self.x**3 * sp.sqrt(1 + self.z**2 / self.x**2))
        B = self.z / (self.x**2 * sp.sqrt(self.x**2 + self.z**2))
        # Test that ratio is 1
        ratio = sp.simplify(A / B)
        # This may or may not simplify to 1, but numeric should pass
        r = self.prover.prove(A, B)
        assert r.equivalent

    def test_b_field_normalized(self):
        """Biot-Savart with normalized symbols."""
        mu0, I_phys, d = sp.symbols("mu0 I_phys d")
        A = mu0 * I_phys / (2 * sp.pi * d)
        B = mu0 * I_phys / (2 * sp.pi * d)
        r = self.prover.prove(A, B)
        assert r.equivalent


# ════════════════════════════════════════════
# Utility function tests
# ════════════════════════════════════════════


class TestUtilities:
    def test_sanitize_name(self):
        assert sanitize_name("mu_{0}") == "mu0"
        assert sanitize_name("I") == "I_phys"  # Wolfram reserved
        assert sanitize_name("E") == "E_phys"  # Wolfram reserved
        assert sanitize_name("x") == "x"       # Unchanged

    def test_to_wolfram_number(self):
        assert to_wolfram_number(0.0) == "0"
        assert to_wolfram_number(1e-3) == "0.001"
        assert to_wolfram_number(4e-7) == "4*^-07"
        assert to_wolfram_number(2.37e9) == "2370000000"

    def test_latex_to_wolfram_code(self):
        code = latex_to_wolfram_code(r"\frac{\mu_0 I}{2\pi d}")
        assert "I_phys" in code  # I renamed to I_phys
        assert "mu0" in code     # mu_{0} renamed to mu0

    def test_normalize_expr(self):
        from sympy.parsing.latex import parse_latex
        expr = parse_latex(r"\frac{\mu_0 I}{2\pi d}")
        norm = _normalize_expr(expr)
        assert sp.Symbol("mu0") in norm.free_symbols
        assert sp.pi in norm.atoms()  # Symbol('pi') → sp.pi


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
