#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test-harness gates for hfpapers-crawler.

Self-contained — zero dependency on hermes-verify or any internal package.

Gate legend:
  F08 — StateHermeticityGate: a test run decides where state goes. A machine-level
        override (``HFPAPERS_DATA_DIR`` pointing at the developer's library, or a
        ``HFPCLAWER_*`` root) must not reach a test, and the artefacts a test can
        create must land inside that test's temp directory.

Why F08 exists: the suite assumed a "clean checkout" — no override exported, no
``config.local.yaml``. On a configured machine that assumption silently inverted:
``HFPAPERS_DATA_DIR`` redirected the fixtures at the *real* store, so a bare
``pytest`` wrote test rows into a 3976-paper library, and two path-invariant tests
went red for a reason that had nothing to do with the code under test. Both
symptoms are the same defect: environment leaking into tests. These tests hold the
line mechanically, because the failure mode is silent — nothing errors, the run is
just wrong.
"""

from __future__ import annotations

import os
from pathlib import Path

# Kept in step with tests/conftest.py (_AMBIENT_CHECKOUT_ENV + the data dir).
_AMBIENT_CHECKOUT_ENV = (
    "HFPCLAWER_STATE_DIR",
    "HFPCLAWER_CONFIG_DIR",
    "HFPCLAWER_CHECKOUT_DIR",
)


def test_ambient_state_overrides_never_reach_a_test():
    """No inherited state override is visible to a test."""
    leaked = [var for var in _AMBIENT_CHECKOUT_ENV if var in os.environ]
    assert not leaked, f"ambient state overrides leaked into the test: {leaked}"


def test_state_artifacts_land_in_the_test_temp_dir(test_env):
    """The database and the positive pool resolve inside this test's temp dir."""
    from hfpapers.paper_store import _db_path
    from hfpapers.pool import default_pool_path

    temp = Path(test_env)
    assert Path(os.environ["HFPAPERS_DATA_DIR"]) == temp / "data"
    for resolved in (Path(_db_path()), default_pool_path()):
        assert temp in resolved.parents, f"{resolved} escapes the per-test temp dir"


def test_state_artifacts_never_land_in_the_working_copy(test_env):
    """...and therefore never inside the repository the suite is running from."""
    import hfpapers
    from hfpapers.paper_store import _db_path
    from hfpapers.pool import default_pool_path

    repo_root = Path(hfpapers.__file__).resolve().parent.parent
    for resolved in (Path(_db_path()), default_pool_path()):
        assert repo_root not in resolved.parents, f"{resolved} is inside the working copy"


def test_explicit_override_in_a_test_still_wins(tmp_path, monkeypatch):
    """The harness clears ambient values; it does not forbid a test setting its own."""
    from hfpapers.paper_store import _db_path

    monkeypatch.setenv("HFPAPERS_DATA_DIR", str(tmp_path / "elsewhere"))
    assert Path(_db_path()).parent == tmp_path / "elsewhere"
