#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backward compatibility shim — redirects to hfpclawer.audit.

This module was replaced by hfpclawer.audit.l1_local in v0.8.0.
Import path preserved for backward compatibility.
"""

import logging
import warnings

warnings.warn(
    "hfpclawer.citation_audit is deprecated — use hfpclawer.audit instead",
    DeprecationWarning, stacklevel=2,
)

from hfpclawer.audit.l1_local import (  # noqa: F401, E402
    check_citation_local as check_citation,
    find_arxiv_db,
    ARXIV_ID_RE,
)
