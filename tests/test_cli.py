#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test CLI -- Typer subcommand invocation + entry point validation

Two layers of testing:
  1. runner.invoke(app, ...) -- fast, in-process Typer tests
  2. subprocess entry point -- real console_scripts execution path
"""

import os
import subprocess
import sys
import tempfile

import pytest
from typer.testing import CliRunner

from hfpapers.cli import app

runner = CliRunner()

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(HERE, ".."))


# -- helpers ---------------------------------------------------


def _entry_script(code: str = "", invokes_app: bool = True) -> str:
    """Build the exact entry point script pip generates for console_scripts"""
    body = code or "from hfpapers.cli import app\nsys.exit(app())\n"
    return "#!/usr/bin/env python3\nimport sys\n" + body


def _run_entry_point(args: list[str], code: str = "") -> subprocess.CompletedProcess:
    """Run a subprocess with the exact entry point invocation"""
    script = _entry_script(code)
    with tempfile.TemporaryDirectory() as tmp:
        script_path = os.path.join(tmp, "hfpclawer_test")
        with open(script_path, "w") as f:
            f.write(script)
        os.chmod(script_path, 0o755)
        return subprocess.run(
            [sys.executable, script_path, *args],
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "PYTHONPATH": PROJECT_ROOT},
        )


def _built_wheel_path() -> str | None:
    """Return path to a pre-built wheel in dist/, or None"""
    dist_dir = os.path.join(PROJECT_ROOT, "dist")
    if not os.path.isdir(dist_dir):
        return None
    candidates = sorted(f for f in os.listdir(dist_dir) if f.endswith(".whl") and "hfpclawer" in f)
    return os.path.join(dist_dir, candidates[-1]) if candidates else None


# -- Entry point tests (subprocess, real console_scripts path) --


class TestEntryPoint:
    """Subprocess entry point validation (real pip console_scripts path)

    These catch import-chain failures that `runner.invoke(app)` misses,
    because running via subprocess exercises entry_point resolution and
    top-level module imports exactly as a pip-installed user sees.
    """

    def test_version(self):
        """Entry point version shows hfpclawer v<semver>"""
        result = _run_entry_point(["version"])
        assert result.returncode == 0, (
            f"entry point version failed:\n  stdout: {result.stdout}\n  stderr: {result.stderr}"
        )
        assert result.stdout.startswith("hfpclawer v")

    def test_help(self):
        """Entry point --help shows hfpclawer usage"""
        result = _run_entry_point(["--help"])
        assert result.returncode == 0
        assert "hfpclawer" in result.stdout
        assert "Usage:" in result.stdout

    def test_download_meta_help(self):
        """Entry point download-meta --help shows the source option.

        `download` now downloads candidate PDFs (`--limit`); the metadata command with
        `--source` was renamed to `download-meta`.
        """
        result = _run_entry_point(["download-meta", "--help"])
        assert result.returncode == 0
        assert "--source" in result.stdout or "source" in result.stdout

    def test_audit_help(self):
        """Entry point audit --help shows subcommand options"""
        result = _run_entry_point(["audit", "--help"])
        assert result.returncode == 0
        assert "ACTION" in result.stdout or "data" in result.stdout

    def test_batch_help(self):
        """Entry point batch --help shows subcommand options"""
        result = _run_entry_point(["batch", "--help"])
        assert result.returncode == 0
        assert "--priority" in result.stdout or "priority" in result.stdout

    def test_invalid_command(self):
        """Entry point with unknown command shows error (exit 2)"""
        result = _run_entry_point(["nonexistent_subcommand_xyz"])
        assert result.returncode == 2
        assert "Error" in result.stderr

    @pytest.mark.slow
    def test_missing_dep_shows_error(self):
        """--no-deps install: error must name the missing module

        Uses a temp venv + pip install --no-deps to reproduce exactly
        what a user with an incomplete install sees.
        """
        wheel = _built_wheel_path()
        if not wheel:
            pytest.skip("No pre-built wheel; run 'python -m build --wheel' first")
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                [sys.executable, "-m", "venv", os.path.join(tmp, "venv")],
                capture_output=True,
                timeout=30,
            )
            pip = os.path.join(tmp, "venv", "bin", "pip")
            hfp = os.path.join(tmp, "venv", "bin", "hfpclawer")
            install = subprocess.run(
                [pip, "install", "--no-deps", wheel],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert install.returncode == 0, f"pip install failed: {install.stderr}"

            result = subprocess.run(
                [hfp, "version"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert result.returncode == 1
            assert "ModuleNotFoundError" in result.stderr
            assert "No module named" in result.stderr


# -- In-process Typer tests (fast, no subprocess) --


class TestCLI:
    """Test CLI invocation and options (in-process via CliRunner)"""

    def test_help(self):
        """--help shows usage, hfpclawer name, and all subcommands"""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output
        assert "hfpclawer" in result.output

        expected_commands = [
            "search",
            "download",
            "convert",
            "full",
            "batch",
            "audit",
            "dedup",
            "list",
            "info",
            "stats",
            "config",
            "store",
            "sniff",
            "mcp",
            "init",
            "monitor",
            "version",
        ]
        for cmd in expected_commands:
            assert cmd in result.output, f"Missing command in --help: {cmd}"

        assert "--verbose" in result.output

    def test_version(self):
        """version command shows hfpclawer v<semver>"""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert result.output.strip().startswith("hfpclawer v")
        import re

        assert re.search(r"v\d+\.\d+\.\d+", result.output)

    def test_no_dash_version_rejected(self):
        """--version is no longer an option — shows error (exit 2)"""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 2
        assert "No such option" in result.output

    def test_version_help(self):
        """version --help shows subcommand info"""
        result = runner.invoke(app, ["version", "--help"])
        assert result.exit_code == 0
        assert "Show version" in result.output

    def test_verbose(self, test_env):
        """-v sets debug level, doesn't crash"""
        result = runner.invoke(app, ["-v", "config"])
        assert result.exit_code == 0

    def test_download_unknown_source(self, test_env):
        """download-meta --source=xzy prints error message"""
        result = runner.invoke(app, ["download-meta", "--source", "xzy"])
        assert result.exit_code == 0
        assert "Unknown" in result.output or "unknown" in result.output

    def test_download_status(self, test_env):
        """download-meta --status runs without crashing (may show empty status)"""
        result = runner.invoke(app, ["download-meta", "--status"])
        assert result.exit_code == 0

    def test_download_help(self, test_env):
        """download-meta --help shows source options (no network IO)"""
        result = runner.invoke(app, ["download-meta", "--help"])
        assert result.exit_code == 0
        assert "--source" in result.output

    def test_batch_defaults(self, test_env):
        """batch --help shows options"""
        result = runner.invoke(app, ["batch", "--help"])
        assert result.exit_code == 0
        assert "--priority" in result.output

    def test_config(self, test_env):
        """config shows current configuration"""
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "search" in result.output

    def test_dedup(self, test_env):
        """dedup shows dedup statistics"""
        result = runner.invoke(app, ["dedup"])
        assert result.exit_code == 0

    def test_search_dry_run(self, test_env):
        """dry-run search (mock network to avoid hang)"""
        from unittest.mock import patch

        with patch("hfpapers.evolved.HFPapersCrawler.crawl", return_value=[]):
            result = runner.invoke(app, ["search", "--dry-run"])
        assert result.exit_code == 0

    def test_search_help(self, test_env):
        """search --help shows options"""
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0
        assert "--max-pages" in result.output

    def test_store_stats(self, test_env):
        """store stats shows paper store statistics"""
        result = runner.invoke(app, ["store", "stats"])
        assert result.exit_code == 0

    def test_list_empty(self):
        """list on empty dedup returns error 1"""
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 1

    def test_info_not_found(self):
        """info with non-existent ID returns error 1"""
        result = runner.invoke(app, ["info", "9999.99999"])
        assert result.exit_code == 1

    def test_info_help(self):
        """info --help shows options"""
        result = runner.invoke(app, ["info", "--help"])
        assert result.exit_code == 0
        assert "ARXIV_ID" in result.output.upper() or "arxiv" in result.output

    def test_convert_no_pdfs(self, test_env):
        """convert with no PDFs returns exit 0 or 1"""
        result = runner.invoke(app, ["convert"])
        assert result.exit_code in (0, 1)

    def test_convert_help(self, test_env):
        """convert --help shows options"""
        result = runner.invoke(app, ["convert", "--help"])
        assert result.exit_code == 0
        assert "--to-wiki" in result.output

    def test_full_help(self):
        """full --help shows options"""
        result = runner.invoke(app, ["full", "--help"])
        assert result.exit_code == 0
        assert "--max-pages" in result.output

    def test_stats(self, test_env):
        """stats command returns data"""
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0

    def test_stats_help(self):
        """stats --help shows options"""
        result = runner.invoke(app, ["stats", "--help"])
        assert result.exit_code == 0

    def test_init_quick(self, test_env):
        """init --quick creates config.yaml in current dir"""
        # Remove any existing config left by test_env fixture
        cfg_path = os.path.join(os.getcwd(), "config.yaml")
        if os.path.exists(cfg_path):
            os.remove(cfg_path)
        result = runner.invoke(app, ["init", "--quick"])
        assert result.exit_code == 0, f"init --quick crashed: {result.exception!r}"
        assert os.path.exists(cfg_path), "init --quick should create config.yaml"
        # Regression: the REPO_USER template contains literal YAML braces, which
        # str.format() consumed → KeyError('file') on every fresh init.
        repo_user = os.path.join(os.getcwd(), "REPO_USER.md")
        assert os.path.exists(repo_user), "init --quick should scaffold REPO_USER.md"
        text = open(repo_user, encoding="utf-8").read()
        assert "{file:" in text, "the YAML template must survive substitution intact"
        assert os.path.basename(os.getcwd()) in text, "project name must be substituted"

    def test_init_existing_config(self, test_env):
        """init when config exists warns and exits gracefully"""
        cfg_path = os.path.join(os.getcwd(), "config.yaml")
        if not os.path.exists(cfg_path):
            with open(cfg_path, "w") as f:
                f.write("existing: true\n")
        result = runner.invoke(app, ["init", "--quick"])
        assert result.exit_code == 0
        assert "already exists" in result.output

    def test_sniff_help(self):
        """sniff --help shows options"""
        result = runner.invoke(app, ["sniff", "--help"])
        assert result.exit_code == 0

    def test_mcp_help(self):
        """mcp --help shows options"""
        result = runner.invoke(app, ["mcp", "--help"])
        assert result.exit_code == 0

    def test_monitor_help(self):
        """monitor --help documents its ACTION argument and --interval.

        Actions (start/stop/status) are argument *values*; they do not appear in the
        help text, so asserting on the action name tested nothing.
        """
        result = runner.invoke(app, ["monitor", "--help"])
        assert result.exit_code == 0
        assert "ACTION" in result.output
        assert "--interval" in result.output

    def test_monitor_status(self, test_env):
        """monitor status shows daemon state (not running by default)"""
        result = runner.invoke(app, ["monitor", "status"])
        assert result.exit_code == 0
        assert "not running" in result.output.lower()

    def test_audit_data(self, test_env):
        """audit data performs data source audit"""
        result = runner.invoke(app, ["audit", "data"])
        assert result.exit_code == 0

    def test_audit_stats(self, test_env):
        """audit stats returns operation statistics"""
        result = runner.invoke(app, ["audit", "stats"])
        assert result.exit_code == 0

    def test_audit_help_with_sub(self, test_env):
        """audit stats --help shows options"""
        result = runner.invoke(app, ["audit", "stats", "--help"])
        assert result.exit_code == 0

    def test_audit_direct_stats(self, test_env):
        """Shorthand: 'audit stats' without 'ops' prefix"""
        result = runner.invoke(app, ["audit", "stats"])
        assert result.exit_code == 0

    def test_unknown_action_shows_error(self):
        """Unknown top-level command shows error (exit 2)"""
        result = runner.invoke(app, ["nonexistent_subcommand_xyz"])
        assert result.exit_code == 2
        assert "Error" in result.output


# -- Store export (stateful, needs test_env) --


class TestStoreExport:
    """Test store export functionality.

    Isolated on purpose: these tests previously ran against the ambient database, so
    "empty store" only held while the developer's real store happened to be empty, and
    the export path was scraped from wrapped console output.
    """

    @pytest.fixture(autouse=True)
    def isolated_data_dir(self, tmp_path, monkeypatch):
        from hfpapers import paper_store

        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("HFPAPERS_DATA_DIR", str(data_dir))
        monkeypatch.setattr(paper_store, "_store_instance", None)
        yield data_dir
        paper_store._store_instance = None

    @staticmethod
    def _exported(data_dir, suffix: str):
        files = sorted(
            data_dir.glob(f"papers_export_*{suffix}"), key=lambda f: f.stat().st_mtime
        )
        assert files, f"no export artifact (*{suffix}) in {data_dir}"
        return files[-1]

    def test_export_json_empty(self, isolated_data_dir):
        """Empty store export reports no papers"""
        result = runner.invoke(app, ["store", "export", "json"])
        assert result.exit_code == 0
        assert "No papers" in result.output or "no papers" in result.output

        assert not list(isolated_data_dir.glob("papers_export_*.json")), (
            "an empty store must not produce an export file"
        )

    def test_export_unsupported_format(self, test_env):
        """Unsupported format returns error 1"""
        result = runner.invoke(app, ["store", "export", "xlsx"])
        assert result.exit_code == 1
        assert "Unsupported" in result.output

    def test_export_json_with_papers(self, isolated_data_dir):
        """Insert a paper, export JSON, verify content"""
        import json

        from hfpapers.paper_store import ensure_paper

        sf_id, _ = ensure_paper("2501.12345", title="Export Test Paper", source="test")
        result = runner.invoke(app, ["store", "export", "json"])
        assert result.exit_code == 0
        assert "Exported" in result.output
        assert ".json" in result.output

        data = json.loads(self._exported(isolated_data_dir, ".json").read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["title"] == "Export Test Paper"
        assert data[0]["sf_id"] == sf_id

    def test_export_csv_with_papers(self, isolated_data_dir):
        """Insert a paper, export CSV, verify content"""
        import csv

        from hfpapers.paper_store import ensure_paper

        ensure_paper("2501.67890", title="CSV Export Paper", source="test")
        result = runner.invoke(app, ["store", "export", "csv"])
        assert result.exit_code == 0
        assert "Exported" in result.output
        assert ".csv" in result.output

        with self._exported(isolated_data_dir, ".csv").open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["title"] == "CSV Export Paper"
