#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hfpclawer -- Multi-source academic paper crawler for OpenClaw or Hermes Agent"""

# PEP 621: pyproject.toml is the single source of truth.
#
# Read the local pyproject.toml first. An installed distribution's metadata goes
# stale as soon as the source version is bumped, so a checkout would keep
# reporting the previously installed version (which made the version gate in
# tests/test_gates.py fail). Fall back to importlib.metadata for the installed
# wheel case, where pyproject.toml is not shipped, then to a sentinel.
import re

from hfpapers import paths

__version__ = "0.0.0"

_checkout = paths.checkout_root()
_pyproject = (_checkout / "pyproject.toml") if _checkout else None
try:
    _match = re.search(
        r'^version\s*=\s*"([^"]+)"', _pyproject.read_text(encoding="utf-8"), re.MULTILINE
    ) if _pyproject is not None else None
    if _match:
        __version__ = _match.group(1)
except OSError:
    pass

if __version__ == "0.0.0":
    try:
        from importlib.metadata import version as _pkg_version

        __version__ = _pkg_version("hfpclawer")
    except Exception:
        pass  # Keep sentinel
