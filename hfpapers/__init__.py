#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hfpclawer -- Multi-source academic paper crawler for OpenClaw or Hermes Agent"""

# Version: single source of truth — match pyproject.toml
# When installed via pip: importlib.metadata takes priority
# When running editable: hardcoded fallback
__version__ = "0.9.12"

try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("hfpclawer")
except Exception:
    pass  # Keep hardcoded fallback
