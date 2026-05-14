#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test CLI — Typer subcommand invocation"""

from typer.testing import CliRunner

from hfpapers.cli import app

runner = CliRunner()


class TestCLI:
    """Test CLI invocation and options"""

    def test_help(self):
        """--help shows usage, hfpclawer name, and all subcommands"""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output
        assert "hfpclawer" in result.output

        # All top-level subcommands must be listed
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
        ]
        for cmd in expected_commands:
            assert cmd in result.output, f"Missing command in --help: {cmd}"

        # --version option must appear
        assert "--version" in result.output

    def test_version(self):
        """--version shows hfpclawer v<semver>"""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert result.output.startswith("hfpclawer v")
        # Version must be semver-like (X.Y.Z)
        import re

        assert re.search(r"v\d+\.\d+\.\d+", result.output)

    def test_verbose(self, test_env):
        """-v sets debug level, doesn't crash"""
        result = runner.invoke(app, ["-v", "config"])
        assert result.exit_code == 0

    def test_config(self, test_env):
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "search" in result.output

    def test_dedup(self, test_env):
        result = runner.invoke(app, ["dedup"])
        assert result.exit_code == 0

    def test_search_dry_run(self, test_env):
        """dry-run search (mock network to avoid hang)"""
        from unittest.mock import patch

        with patch("hfpapers.evolved.HFPapersCrawler.crawl", return_value=[]):
            result = runner.invoke(app, ["search", "--dry-run"])
        assert result.exit_code == 0

    def test_store_stats(self, test_env):
        result = runner.invoke(app, ["store", "stats"])
        assert result.exit_code == 0

    def test_list_empty(self):
        result = runner.invoke(app, ["list"])
        assert result.exit_code in (0, 1)

    def test_info_not_found(self):
        result = runner.invoke(app, ["info", "9999.99999"])
        assert result.exit_code == 1

    def test_convert_no_pdfs(self, test_env):
        result = runner.invoke(app, ["convert"])
        assert result.exit_code in (0, 1)


class TestStoreExport:
    """Test store export functionality"""

    def test_export_json_empty(self, test_env):
        """Empty store export JSON should raise error"""
        result = runner.invoke(app, ["store", "export", "json"])
        assert result.exit_code == 0
        assert "No papers" in result.output or "no papers" in result.output

    def test_export_unsupported_format(self, test_env):
        result = runner.invoke(app, ["store", "export", "xlsx"])
        assert result.exit_code == 1
        assert "Unsupported" in result.output

    def test_export_json_with_papers(self, test_env):
        """Insert a paper first, then export JSON"""
        from hfpapers.paper_store import ensure_paper

        sf_id, is_new = ensure_paper("2501.12345", title="Export Test Paper", source="test")
        result = runner.invoke(app, ["store", "export", "json"])
        assert result.exit_code == 0
        assert "Exported" in result.output
        assert ".json" in result.output

        # Verify file content
        import json

        output_line = [l for l in result.output.split("\n") if l.strip().startswith("/")][0]
        out_path = output_line.strip()
        with open(out_path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) >= 1
        paper = data[0]
        assert paper["title"] == "Export Test Paper"
        assert paper["sf_id"] == sf_id

    def test_export_csv_with_papers(self, test_env):
        from hfpapers.paper_store import ensure_paper

        ensure_paper("2501.67890", title="CSV Export Paper", source="test")
        result = runner.invoke(app, ["store", "export", "csv"])
        assert result.exit_code == 0
        assert "Exported" in result.output
        assert ".csv" in result.output

        # Verify CSV content
        import csv

        output_line = [l for l in result.output.split("\n") if l.strip().startswith("/")][0]
        out_path = output_line.strip()
        with open(out_path, newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        assert len(rows) >= 2  # header + data
        assert rows[0][0] == "sf_id"
        assert rows[1][1] == "CSV Export Paper"

    def test_export_via_paperstore_direct(self, paper_store):
        """Directly test PaperStore.export_papers() method"""
        # Insert a few papers first
        from hfpapers.paper_store import PaperRecord

        for i in range(3):
            r = PaperRecord(title=f"Test Paper {i}", source="direct_test")
            paper_store.upsert_paper(r)

        # JSON export
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

        # CSV export
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
