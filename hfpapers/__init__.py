#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hfpclawer -- Multi-source academic paper crawler for OpenClaw or Hermes Agent"""

try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("hfpclawer")
except Exception:
    __version__ = "0.0.0"
