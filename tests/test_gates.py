#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verification gates for hfpapers-crawler (public PyPI package).

Self-contained — zero dependency on hermes-verify or any internal package.
Uses standard pytest markers registered in pyproject.toml.

Gate legend:
  B10 — SnowflakeGate: Snowflake ID uniqueness, monotonicity, timestamp
  B11 — PaperStoreGate: PaperStore CRUD operations
  C01 — CLIGate: CLI subcommand registration tree
  C02 — DedupGate: DedupEngine deduplication correctness
  F01 — ConfigGate: YAML config loading + env override
  F02 — VersionGate: Package version consistency + import structure
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest


# ═════════════════════════════════════════════════════════════════
# B10 — SnowflakeGate: Snowflake ID 生成验证
# ═════════════════════════════════════════════════════════════════

pytestmark_gate_b = pytest.mark.gate_b


class TestSnowflakeGate:
    """B10: Snowflake ID generator correctness."""

    def test_snowflake_id_uniqueness(self):
        from hfpapers.paper_store import snowflake_id
        ids = {snowflake_id() for _ in range(100)}
        assert len(ids) == 100

    def test_snowflake_id_increasing_with_gap(self):
        import time
        from hfpapers.paper_store import snowflake_id
        id1 = snowflake_id()
        time.sleep(0.002)
        id2 = snowflake_id()
        assert id2 > id1

    def test_snowflake_id_is_positive_int(self):
        from hfpapers.paper_store import snowflake_id
        sf_id = snowflake_id()
        assert isinstance(sf_id, int)
        assert sf_id > 0

    def test_snowflake_timestamp_returns_datetime(self):
        from datetime import datetime
        from hfpapers.paper_store import snowflake_id, snowflake_timestamp
        sf_id = snowflake_id()
        ts = snowflake_timestamp(sf_id)
        assert isinstance(ts, datetime)
        assert ts.year >= 2024

    def test_snowflake_worker_differs(self):
        from hfpapers.paper_store import snowflake_id
        id1 = snowflake_id(worker_id=0)
        id2 = snowflake_id(worker_id=1)
        assert id1 != id2


# ═════════════════════════════════════════════════════════════════
# B11 — PaperStoreGate: PaperStore CRUD 验证
# ═════════════════════════════════════════════════════════════════


class TestPaperStoreGate:
    """B11: PaperStore CRUD operations with temp-file backend."""

    @pytest.fixture
    def store(self):
        from hfpapers.paper_store import PaperStore
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        s = PaperStore(db_path=path)
        yield s
        try:
            os.unlink(path)
        except OSError:
            pass

    def test_store_has_tables(self, store):
        import sqlite3
        conn = sqlite3.connect(store.db_path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "papers" in tables
        assert "identifiers" in tables

    def test_upsert_and_retrieve(self, store):
        from hfpapers.paper_store import PaperRecord
        sf_id = store.upsert_paper(PaperRecord(
            title="Test Paper", abstract="abstract",
            year=2025, source="test", relevance=80,
        ))
        assert sf_id > 0
        got = store.get_paper_by_id(sf_id)
        assert got is not None
        assert got.title == "Test Paper"
        assert got.relevance == 80

    def test_update_paper(self, store):
        from hfpapers.paper_store import PaperRecord
        sf_id = store.upsert_paper(PaperRecord(title="Original", relevance=50))
        store.update_paper(sf_id, relevance=90)
        got = store.get_paper_by_id(sf_id)
        assert got.relevance == 90

    def test_get_nonexistent_returns_none(self, store):
        got = store.get_paper_by_id(99999)
        assert got is None

    def test_ensure_paper_dedup(self):
        from hfpapers.paper_store import ensure_paper
        sf1, new1 = ensure_paper(arxiv_id="2501.00001", title="Paper A")
        assert new1 is True
        sf2, new2 = ensure_paper(arxiv_id="2501.00001", title="Paper A")
        assert new2 is False
        assert sf2 == sf1


# ═════════════════════════════════════════════════════════════════
# C01 — CLIGate: CLI 子命令树验证
# ═════════════════════════════════════════════════════════════════

pytestmark_gate_c = pytest.mark.gate_c


class TestCLIGate:
    """C01: CLI subcommand registration tree."""

    @staticmethod
    def _require_typer():
        return pytest.importorskip("typer", reason="typer required for CLI tests")

    def test_cli_import(self):
        self._require_typer()
        from hfpapers.cli import app
        assert app is not None

    def test_cli_core_commands(self):
        self._require_typer()
        from hfpapers.cli import app
        names = {c.name for c in app.registered_commands}
        for cmd in ("version", "search", "download", "convert", "full",
                     "list", "info", "stats", "config"):
            assert cmd in names, f"Missing command: {cmd}"

    def test_cli_extended_commands(self):
        self._require_typer()
        from hfpapers.cli import app
        names = {c.name for c in app.registered_commands}
        for cmd in ("sniff", "analyze", "wiki", "store", "audit", "check", "mcp"):
            assert cmd in names, f"Missing command: {cmd}"

    def test_cli_verify_group(self):
        self._require_typer()
        from hfpapers.cli import app
        assert "verify" in {g for g in app.registered_groups}

    def test_cli_version_runs(self):
        self._require_typer()
        from typer.testing import CliRunner
        from hfpapers.cli import app
        result = CliRunner().invoke(app, ["version"])
        assert result.exit_code == 0
        assert "hfpclawer v" in result.stdout


# ═════════════════════════════════════════════════════════════════
# C02 — DedupGate: Dedup 引擎验证
# ═════════════════════════════════════════════════════════════════


class TestDedupGate:
    """C02: DedupEngine deduplication correctness."""

    def test_dedup_engine_has_expected_methods(self, test_env):
        from hfpapers.evolved import DedupEngine
        engine = DedupEngine()
        assert hasattr(engine, "count")
        assert hasattr(engine, "is_duplicate")
        assert hasattr(engine, "add")

    def test_is_duplicate_nonexistent(self, test_env):
        from hfpapers.evolved import DedupEngine, PaperInfo
        engine = DedupEngine()
        p = PaperInfo(arxiv_id="9999.99999", title="Nonexistent")
        assert engine.is_duplicate(p) is None

    def test_paper_info_dataclass(self):
        from hfpapers.evolved import PaperInfo
        p = PaperInfo(arxiv_id="2001.08361", title="FNO", relevance=80)
        assert p.arxiv_id == "2001.08361"
        assert p.relevance == 80
        assert p.categories == []

    def test_ensure_paper_dedup_via_store(self):
        from hfpapers.paper_store import ensure_paper
        sf1, _ = ensure_paper(arxiv_id="2501.00001", title="Paper A")
        sf2, new2 = ensure_paper(arxiv_id="2501.00001", title="Paper A")
        assert new2 is False
        assert sf2 == sf1


# ═════════════════════════════════════════════════════════════════
# F01 — ConfigGate: 配置加载验证
# ═════════════════════════════════════════════════════════════════

pytestmark_gate_f = pytest.mark.gate_f


class TestConfigGate:
    """F01: YAML config loading + env override."""

    def test_config_loads_defaults(self):
        from hfpapers.config import load_config, get
        cfg = load_config(reload=True)
        assert isinstance(cfg, dict)
        assert get("paths.pdf_dir") is not None

    def test_config_has_search_queries(self):
        from hfpapers.config import get
        queries = get("search.queries")
        assert queries is not None and len(queries) >= 1

    def test_config_has_keyword_filters(self):
        from hfpapers.config import get
        assert get("keywords.include_high") is not None
        assert get("keywords.exclude") is not None

    def test_price_lookup_not_crash(self):
        from hfpapers.config import get_price
        price = get_price("deepseek/deepseek-chat")
        assert isinstance(price, dict)


# ═════════════════════════════════════════════════════════════════
# F02 — VersionGate: 版本一致性 + 导入结构
# ═════════════════════════════════════════════════════════════════


class TestVersionGate:
    """F02: Package version consistency + import structure."""

    REPO_ROOT = Path(__file__).resolve().parent.parent

    def test_package_version_defined(self):
        from hfpapers import __version__
        assert __version__ and isinstance(__version__, str)

    def test_version_matches_pyproject(self):
        import tomllib
        from hfpapers import __version__
        data = tomllib.loads(
            (self.REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        assert __version__ == data.get("project", {}).get("version", "")

    def test_core_modules_importable(self):
        for mod in ("hfpapers.config", "hfpapers.paper_store",
                     "hfpapers.evolved", "hfpapers.hardware"):
            __import__(mod)

    def test_cli_entry_point_defined(self):
        import tomllib
        data = tomllib.loads(
            (self.REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        assert "hfpclawer" in data.get("project", {}).get("scripts", {})

    def test_license_file_exists(self):
        assert (self.REPO_ROOT / "LICENSE").exists()

    def test_readme_exists(self):
        assert (self.REPO_ROOT / "README.md").exists()

    def test_config_example_exists(self):
        assert (self.REPO_ROOT / "config.yaml.example").exists()

    def test_no_internal_deps(self):
        import tomllib
        data = tomllib.loads(
            (self.REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        deps = data.get("project", {}).get("dependencies", [])
        for dep in deps:
            assert "hermes-verify" not in dep
            assert "hermes_verify" not in dep
