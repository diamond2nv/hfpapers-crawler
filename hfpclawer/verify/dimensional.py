#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dimensional.py — L3: Physical dimension analysis via pint.

Each function accepts a value (float, Quantity, or string) and a
target dimension name to verify.  Returns the magnitude and whether
the dimension matches.

Supported dimensions (via pint):
    "magnetic flux density"   → T (tesla)
    "magnetic field strength" → A/m
    "length"                  → m
    "temperature"             → K
    "frequency"               → Hz
    "electric current"        → A
    "dimensionless"           → pure number

Graceful degradation: missing pint → warnings, not errors.
"""

import logging

logger = logging.getLogger("hfpclawer.verify.dimensional")

try:
    import pint

    _UREG = pint.UnitRegistry()
    _HAS_PINT = True
except ImportError:
    _HAS_PINT = False
    logger.warning("pint not available; dimensional checks disabled")


# ─── Known dimension map ────────────────────
# Maps: our dimension name → (pint unit string, pint dimension string)
_DIMENSION_MAP: dict[str, tuple[str, str]] = {
    "magnetic flux density": ("T", "[length] ** -1 * [mass] * [time] ** -2 * [current] ** -1"),
    "magnetic field strength": ("A/m", "[current] / [length]"),
    "length": ("m", "[length]"),
    "temperature": ("K", "[temperature]"),
    "frequency": ("Hz", "1 / [time]"),
    "electric current": ("A", "[current]"),
    "electric potential": ("V", "[length] ** 2 * [mass] * [time] ** -3 * [current] ** -1"),
    "energy": ("J", "[length] ** 2 * [mass] / [time] ** 2"),
    "force": ("N", "[length] * [mass] / [time] ** 2"),
    "pressure": ("Pa", "[mass] / [length] / [time] ** 2"),
    "velocity": ("m/s", "[length] / [time]"),
    "acceleration": ("m/s**2", "[length] / [time] ** 2"),
    "area": ("m**2", "[length] ** 2"),
    "volume": ("m**3", "[length] ** 3"),
    "dimensionless": ("", "dimensionless"),
}


def check_dimension(unit_str: str, target_name: str, label: str = "") -> tuple[float, bool]:
    """Check that a unit string has the expected physical dimension.

    Args:
        unit_str: Unit string understood by pint (e.g. "T", "J", "m/s")
        target_name: Key into _DIMENSION_MAP (e.g. "magnetic flux density")
        label: Human-readable name for error messages.

    Returns:
        (magnitude_in_SI, passed)
    """
    if not _HAS_PINT:
        logger.debug("pint unavailable; assuming dimension OK for %s", label or target_name)
        return 0.0, True

    expected = _DIMENSION_MAP.get(target_name)
    if expected is None:
        logger.warning("Unknown dimension target: %s", target_name)
        return 0.0, False

    expected_unit, _ = expected

    try:
        # Use the value as a quantity (if non-empty) else the expected unit
        if unit_str:
            q = _UREG.Quantity(f"1 {unit_str}")
        elif expected_unit:
            q = _UREG.Quantity(f"1 {expected_unit}")
        else:
            q = _UREG.Quantity(1.0)

        expected_q = _UREG.Quantity(f"1 {expected_unit}") if expected_unit else _UREG.Quantity(1.0)

        if q.dimensionality == expected_q.dimensionality:
            return float(q.to_base_units().magnitude), True

        logger.warning(
            "%s: expected dim=%s (via %s), got dim=%s (via %s)",
            label or target_name, expected_q.dimensionality, expected_unit,
            q.dimensionality, unit_str or expected_unit,
        )
        return float(q.to_base_units().magnitude), False

    except (pint.errors.DimensionalityError, pint.errors.UndefinedUnitError,
            TypeError, ValueError) as exc:
        logger.warning("%s: dimension check failed: %s", label or target_name, exc)
        return 0.0, False


def check_dimensionless(value, label: str = "") -> tuple[float, bool]:
    """Check that a value is dimensionless (pure number)."""
    return check_dimension("", "dimensionless", label)


def check_b_field(value, label: str = "B") -> tuple[float, bool]:
    """Check magnetic flux density (Tesla)."""
    return check_dimension(value, "magnetic flux density", label)


def check_h_field(value, label: str = "H") -> tuple[float, bool]:
    """Check magnetic field strength (A/m)."""
    return check_dimension(value, "magnetic field strength", label)


def check_length(value, label: str = "L") -> tuple[float, bool]:
    """Check length (m)."""
    return check_dimension(value, "length", label)


def check_temperature(value, label: str = "T") -> tuple[float, bool]:
    """Check temperature (K)."""
    return check_dimension(value, "temperature", label)


def check_frequency(value, label: str = "f") -> tuple[float, bool]:
    """Check frequency (Hz)."""
    return check_dimension(value, "frequency", label)


def check_energy(value, label: str = "E") -> tuple[float, bool]:
    """Check energy (J)."""
    return check_dimension(value, "energy", label)
