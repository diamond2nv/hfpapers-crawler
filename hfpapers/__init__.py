#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hfpclawer -- Multi-source academic paper crawler for OpenClaw or Hermes Agent"""

# PEP 621: pyproject.toml is the single source of truth.
# importlib.metadata reads the installed package's pyproject.toml.
# The sentinel "0.0.0" signals the editable/uninstalled case.
__version__ = "0.0.0"

try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("hfpclawer")
except Exception:
    pass  # Keep sentinel
