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
import re
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
        # Commands defined via @app.command() show callback function name
        names = {c.callback.__name__ for c in app.registered_commands
                 if hasattr(c, "callback") and c.callback is not None}
        # Some commands use explicit name (e.g. list=list_papers, download-meta=download_meta)
        names |= {c.name for c in app.registered_commands if c.name is not None}
        for cmd in ("version", "search", "download", "convert", "full",
                     "list", "info", "stats"):
            assert cmd in names, f"Missing command: {cmd}"

    def test_cli_extended_commands(self):
        self._require_typer()
        from hfpapers.cli import app
        names = {c.callback.__name__ for c in app.registered_commands
                 if hasattr(c, "callback") and c.callback is not None}
        names |= {c.name for c in app.registered_commands if c.name is not None}
        for cmd in ("audit", "cron", "zotero", "graph", "download_meta"):
            assert cmd in names, f"Missing command: {cmd}"

    def test_cli_verify_group(self):
        self._require_typer()
        from hfpapers.cli import app
        group_names = {g.name for g in app.registered_groups
                       if hasattr(g, "name")}
        assert "verify" in group_names, "Missing group: verify"

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
        from hfpapers.config import get, load_config
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


# ═════════════════════════════════════════════════════════════════
# F03 — ChangelogGate: 每个版本必须有 changelog 条目
# ═════════════════════════════════════════════════════════════════
#
# Why a gate: 18 tagged releases (v0.17.0 - v0.18.14) shipped with no entries, and
# nothing in the repo could have noticed — the changelog was only mentioned in a docs
# table. The check is not re-implemented here: the test drives the same script that
# scripts/release.sh calls, so the rule has exactly one home.


class TestChangelogGate:
    """F03: every release has a changelog entry (via scripts/changelog_guard.py)."""

    REPO_ROOT = Path(__file__).resolve().parent.parent
    GUARD = REPO_ROOT / "scripts" / "changelog_guard.py"
    CHANGELOG = REPO_ROOT / "docs" / "CHANGELOG.md"

    def _run(self, *args: str):
        import subprocess
        import sys
        return subprocess.run(
            [sys.executable, str(self.GUARD), *args],
            capture_output=True,
            text=True,
        )

    def _current_version(self) -> str:
        import tomllib
        data = tomllib.loads((self.REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return data["project"]["version"]

    def test_guard_script_exists(self):
        assert self.GUARD.is_file(), "the shared changelog guard is the contract"

    def test_current_version_is_documented(self):
        version = self._current_version()
        result = self._run(version)
        assert result.returncode == 0, (
            f"v{version} (pyproject.toml) has no changelog entry.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_historical_version_is_documented(self):
        """Rotation must not make an old release look undocumented.

        v0.16.0 lives in docs/CHANGELOG-archive.md since the window was bounded, so this
        asserts the guard searches the archive as well as the live file.
        """
        result = self._run("0.16.0")
        assert result.returncode == 0, result.stderr
        assert "CHANGELOG-archive.md" in result.stdout

    def test_undocumented_version_fails_loudly(self):
        result = self._run("99.99.99")
        assert result.returncode == 1
        assert "99.99.99" in result.stderr
        assert "## [" in result.stderr, "the failure must show the expected entry shape"

    def test_version_prefix_is_not_a_match(self, tmp_path):
        """`v1.2.10` must not satisfy a lookup for `1.2.1` (substring traps)."""
        fake = tmp_path / "CHANGELOG.md"
        fake.write_text(
            "# CHANGELOG\n\n## [2026-01-01] feat | v1.2.10 — only the longer version exists\n",
            encoding="utf-8",
        )
        nowhere = str(tmp_path / "no-archive.md")
        long_one = self._run("1.2.10", "--changelog", str(fake), "--archive", nowhere, "--quiet")
        short_one = self._run("1.2.1", "--changelog", str(fake), "--archive", nowhere)
        assert long_one.returncode == 0, long_one.stderr
        assert short_one.returncode == 1, "prefix must not count as documented"

    def test_public_line_entries_do_not_satisfy_the_gate(self, tmp_path):
        """Public-line recuts are `###` subsections; only `##` entries count."""
        fake = tmp_path / "CHANGELOG.md"
        fake.write_text(
            "# CHANGELOG\n\n## Public line — sanitized recuts\n\n"
            "### [2026-01-01] fix | v1.2.3 — a recut, not a release entry\n",
            encoding="utf-8",
        )
        result = self._run(
            "1.2.3", "--changelog", str(fake), "--archive", str(tmp_path / "no-archive.md")
        )
        assert result.returncode == 1, "a subsection must not satisfy a release entry"

    def test_guard_rejects_non_semver(self):
        assert self._run("not-a-version").returncode == 2

    def test_guard_reports_missing_changelog(self, tmp_path):
        result = self._run("0.18.15", "--changelog", str(tmp_path / "nope.md"))
        assert result.returncode == 2

    def test_archive_is_searched_too(self, tmp_path):
        """A version that only exists in the archive is still documented."""
        live = tmp_path / "CHANGELOG.md"
        arch = tmp_path / "CHANGELOG-archive.md"
        live.write_text("# CHANGELOG\n\n## [2026-02-01] feat | v2.0.0 — live\n", encoding="utf-8")
        arch.write_text("# archive\n\n## [2026-01-01] fix | v1.0.0 — rotated out\n", encoding="utf-8")
        only_archived = self._run("1.0.0", "--changelog", str(live), "--archive", str(arch))
        assert only_archived.returncode == 0, only_archived.stderr


# ═════════════════════════════════════════════════════════════════
# F04 — ChangelogWindowGate: 变更日志是滚动窗口，不是无限增长的文件
# ═════════════════════════════════════════════════════════════════
#
# A changelog is read, not diffed. Without a bound it grows without limit (v0.18.15
# shipped a 44 KB file), so the window is capped in bytes and rotated into
# docs/CHANGELOG-archive.md. Rule and implementation: scripts/changelog_rotate.py.


class TestChangelogWindowGate:
    """F04: the live changelog stays inside its byte budget and rotation loses nothing."""

    REPO_ROOT = Path(__file__).resolve().parent.parent
    TOOL = REPO_ROOT / "scripts" / "changelog_rotate.py"
    CHANGELOG = REPO_ROOT / "docs" / "CHANGELOG.md"
    ARCHIVE = REPO_ROOT / "docs" / "CHANGELOG-archive.md"

    def _run(self, *args: str):
        import subprocess
        import sys
        return subprocess.run(
            [sys.executable, str(self.TOOL), *args], capture_output=True, text=True
        )

    def _headings(self, path: Path) -> list[str]:
        return re.findall(r"^## \[.*$", path.read_text(encoding="utf-8"), re.MULTILINE)

    def test_tool_exists(self):
        assert self.TOOL.is_file(), "the rotation rule lives in one place"

    def test_live_changelog_is_within_budget(self):
        result = self._run("--check")
        assert result.returncode == 0, (
            f"docs/CHANGELOG.md is over budget — run: python3 scripts/changelog_rotate.py\n"
            f"{result.stderr}"
        )

    def test_window_is_self_describing(self):
        text = self.CHANGELOG.read_text(encoding="utf-8")
        assert re.search(r"<!-- changelog-window rule=\"bytes<=\d+\" kept=\d+ of=\d+", text), (
            "the window must state its own rule and state"
        )

    def test_no_entry_was_lost_across_rotations(self):
        """Rotation moves entries; it must never lose one (checked against HEAD)."""
        result = self._run("--verify-history")
        assert result.returncode == 0, (
            f"a changelog entry that exists at HEAD is missing from live+archive:\n{result.stderr}"
        )

    def test_archive_exists_and_no_entry_appears_in_both_files(self):
        assert self.ARCHIVE.is_file()
        live, archived = set(self._headings(self.CHANGELOG)), set(self._headings(self.ARCHIVE))
        assert live, "live changelog has no entries"
        assert not (live & archived), f"entries in both files: {sorted(live & archived)[:3]}"

    def test_rotation_is_idempotent(self, tmp_path):
        """Rotating a file already inside the budget changes nothing."""
        src = tmp_path / "CHANGELOG.md"
        src.write_text(
            "# CHANGELOG\n\n" + "\n\n".join(
                f"## [2026-01-{i:02d}] feat | v1.0.{i} — entry {i}\n- body {i}" for i in range(1, 11)
            ) + "\n",
            encoding="utf-8",
        )
        before = src.read_bytes()
        first = self._run("--changelog", str(src), "--archive", str(tmp_path / "a.md"))
        second = self._run("--changelog", str(src), "--archive", str(tmp_path / "a.md"))
        assert first.returncode == 0 and second.returncode == 0
        assert src.read_bytes() == before, "an in-budget changelog must not be rewritten"

    def test_rotation_loses_nothing(self, tmp_path):
        src = tmp_path / "CHANGELOG.md"
        arch = tmp_path / "archive.md"
        entries = [
            f"## [2026-01-{i:02d}] feat | v1.0.{i} — entry {i}\n- " + ("x" * 200)
            for i in range(1, 13)
        ]
        src.write_text("# CHANGELOG\n\n" + "\n\n".join(entries) + "\n", encoding="utf-8")
        result = self._run("--changelog", str(src), "--archive", str(arch), "--budget", "1200")
        assert result.returncode == 0, result.stderr
        live, archived = self._headings(src), self._headings(arch)
        assert len(live) + len(archived) == len(entries), "an entry went missing"
        assert len(set(live) | set(archived)) == len(entries), "an entry was duplicated"
        assert len(live) >= 8, "the floor of 8 kept entries was violated"
        assert archived == self._headings(arch)[: len(archived)], "archive must stay newest-first"

    def test_rotation_refuses_below_the_floor(self, tmp_path):
        """Few entries + a tiny budget: exceed the budget rather than lose history."""
        src = tmp_path / "CHANGELOG.md"
        entries = [f"## [2026-01-0{i}] feat | v1.0.{i} — e{i}\n- " + ("y" * 500) for i in range(1, 5)]
        src.write_text("# CHANGELOG\n\n" + "\n\n".join(entries) + "\n", encoding="utf-8")
        before = src.read_bytes()
        result = self._run("--changelog", str(src), "--archive", str(tmp_path / "a.md"), "--budget", "300")
        assert result.returncode == 0
        assert src.read_bytes() == before, "below the floor the file must be left alone"
