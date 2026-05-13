#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
conftest.py — Global project fixtures
"""

import os
import tempfile

import pytest


# ─── Test-specific configuration ───
@pytest.fixture(autouse=True)
def test_env():
    """Isolated test environment: temp directory + temp database"""
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)
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
