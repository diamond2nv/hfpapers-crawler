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

    def test_download_help(self):
        """Entry point download --help shows subcommand options"""
        result = _run_entry_point(["download", "--help"])
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
        """download --source=xzy prints error message"""
        result = runner.invoke(app, ["download", "--source", "xzy"])
        assert result.exit_code == 0
        assert "Unknown" in result.output or "unknown" in result.output

    def test_download_status(self, test_env):
        """download --status runs without crashing (may show empty status)"""
        result = runner.invoke(app, ["download", "--status"])
        assert result.exit_code == 0

    def test_download_help(self, test_env):
        """download --help shows source options (no network IO)"""
        result = runner.invoke(app, ["download", "--help"])
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
        assert result.exit_code == 0
        assert os.path.exists(cfg_path), "init --quick should create config.yaml"

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
        """monitor --help shows options"""
        result = runner.invoke(app, ["monitor", "--help"])
        assert result.exit_code == 0
        assert "start" in result.output

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
    """Test store export functionality"""

    def test_export_json_empty(self, test_env):
        """Empty store export reports no papers"""
        result = runner.invoke(app, ["store", "export", "json"])
        assert result.exit_code == 0
        assert "No papers" in result.output or "no papers" in result.output

    def test_export_unsupported_format(self, test_env):
        """Unsupported format returns error 1"""
        result = runner.invoke(app, ["store", "export", "xlsx"])
        assert result.exit_code == 1
        assert "Unsupported" in result.output

    def test_export_json_with_papers(self, test_env):
        """Insert a paper, export JSON, verify content"""
        from hfpapers.paper_store import ensure_paper

        sf_id, _ = ensure_paper("2501.12345", title="Export Test Paper", source="test")
        result = runner.invoke(app, ["store", "export", "json"])
        assert result.exit_code == 0
        assert "Exported" in result.output
        assert ".json" in result.output

        import json

        output_line = [line for line in result.output.split("\n") if line.strip().startswith("/")][
            0
        ]
        out_path = output_line.strip()
        with open(out_path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) >= 1
        paper = data[0]
        assert paper["title"] == "Export Test Paper"
        assert paper["sf_id"] == sf_id

    def test_export_csv_with_papers(self, test_env):
        """Insert a paper, export CSV, verify content"""
        from hfpapers.paper_store import ensure_paper

        ensure_paper("2501.67890", title="CSV Export Paper", source="test")
        result = runner.invoke(app, ["store", "export", "csv"])
        assert result.exit_code == 0
        assert "Exported" in result.output
        assert ".csv" in result.output

        import csv

        output_line = [line for line in result.output.split("\n") if line.strip().startswith("/")][
            0
        ]
        out_path = output_line.strip()
        with open(out_path, newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        assert len(rows) >= 2  # header + data
        assert rows[0][0] == "sf_id"
        assert rows[1][1] == "CSV Export Paper"

    def test_export_via_paperstore_direct(self, paper_store):
        """Directly test PaperStore.export_papers() method"""
        from hfpapers.paper_store import PaperRecord

        for i in range(3):
            r = PaperRecord(title=f"Test Paper {i}", source="direct_test")
            paper_store.upsert_paper(r)

        import json
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            tmp = f.name
        try:
            out = paper_store.export_papers(format="json", filepath=tmp)
            with open(out) as f:
                data = json.load(f)
            assert len(data) == 3
            assert data[0]["title"].startswith("Test Paper")
        finally:
            import os

            if os.path.exists(tmp):
                os.unlink(tmp)

        import csv

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            tmp = f.name
        try:
            out = paper_store.export_papers(format="csv", filepath=tmp)
            with open(out, newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            assert len(rows) == 4  # header + 3 data
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
