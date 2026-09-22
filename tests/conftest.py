#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
conftest.py — Global project fixtures
"""

import os
import tempfile

import pytest

# Third-party chatter must not land on pytest's capture streams. PyMuPDF >= 1.28
# announces its deprecated `fitz` alias with print(); a module first imported under one
# test's capture keeps that (by then closed) file object, so a later test dies with
# "ValueError: I/O operation on closed file" instead of seeing a warning — the failure
# points at the test, not at the library. Redirected once, at collection time, and only
# if the developer has not chosen a target themselves.
os.environ.setdefault(
    "PYMUPDF_MESSAGE", f"path:{tempfile.gettempdir()}/hfpclawer-pymupdf-message.log"
)

# ─── State overrides that must never reach a test ───
# A developer machine may export HFPAPERS_DATA_DIR (the database location) or the
# HFPCLAWER_* roots. Those values are *environment*, not test inputs: inherited into
# a test run they silently redirect the suite at the real store, so a bare `pytest`
# writes the developer's papers.db (found on a LAN peer: a test row in a 3976-paper
# library). The fixtures below decide where state goes; ambient overrides are cleared
# for every test. Tests that assert the resolution rules set or unset these themselves,
# which lands after this fixture and therefore still wins. Gate: F08
# (tests/test_isolation.py).
_DATA_DIR_ENV = "HFPAPERS_DATA_DIR"
_AMBIENT_CHECKOUT_ENV = (
    "HFPCLAWER_STATE_DIR",
    "HFPCLAWER_CONFIG_DIR",
    "HFPCLAWER_CHECKOUT_DIR",
)
# Everything this fixture rewrites, so it can put the machine's values back.
_STATE_OVERRIDE_ENV = (_DATA_DIR_ENV, *_AMBIENT_CHECKOUT_ENV)


# ─── Test-specific configuration ───
@pytest.fixture(autouse=True)
def test_env():
    """Isolated test environment: temp directory + temp database"""
    old_cwd = os.getcwd()
    saved_env = {var: os.environ.get(var) for var in _STATE_OVERRIDE_ENV}
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)
        # Hermetic state: the database and the positive pool (the two artefacts a test
        # can actually create) live under this test's temp dir, so no test can write
        # the real library, whatever the machine exports.
        os.environ["HFPAPERS_DATA_DIR"] = os.path.join(tmpdir, "data")
        for var in _AMBIENT_CHECKOUT_ENV:
            os.environ.pop(var, None)
        # Create minimal config.yaml
        cfg_path = os.path.join(tmpdir, "config.yaml")
        with open(cfg_path, "w") as f:
            f.write("""
search:
  max_per_dim: 5
  queries:
    - query: "neural operator"
      category: neural-operator
keywords:
  include_high:
    - "neural operator"
    - "pde"
  exclude:
    - "quantum"
    - "llm"
classification:
  threshold_pass: 30
  title_similarity_min: 0.40
paths:
  data_dir: "data"
  pdf_dir: "pdfs"
  md_dir: "mds"
  global_dedup: "crawled.json"
""")
        # Set env var pointing to test config (config.py load_config() prefers this)
        os.environ["_TEST_HFPAPERS_CONFIG"] = cfg_path
        # Force reload config so fixture config takes effect
        import hfpapers.config as _cfg

        _cfg._config_cache = None
        _cfg.load_config(reload=True)
        # Reset global singletons to avoid cross-test contamination
        import hfpapers.paper_store as _ps

        _ps._store_instance = None
        _ps._crossref_instance = None

        yield tmpdir
        os.chdir(old_cwd)
        # Cleanup global singletons (for subsequent tests)
        import hfpapers.paper_store as _ps

        _ps._store_instance = None
        _ps._crossref_instance = None

    # Put the machine's own values back (outside the temp-dir context, so a test that
    # deleted its cwd cannot turn restoration into a second failure).
    for _var, _value in saved_env.items():
        if _value is None:
            os.environ.pop(_var, None)
        else:
            os.environ[_var] = _value


@pytest.fixture
def paper_store():
    """Temporary paper_store instance (in-memory)"""
    import tempfile

    from hfpapers.paper_store import PaperStore

    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    store = PaperStore(db_path=db_path)
    yield store
    try:
        if os.path.exists(db_path):
            os.unlink(db_path)
            if os.path.exists(db_path + "-wal"):
                os.unlink(db_path + "-wal")
    except Exception:
        pass
