"""测试 CLI — Typer 子命令调用"""
from typer.testing import CliRunner
from hfpapers.cli import app

runner = CliRunner()


class TestCLI:
    def test_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output
        assert "hfpclawer" in result.output

    def test_config(self, test_env):
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "search" in result.output

    def test_dedup(self, test_env):
        result = runner.invoke(app, ["dedup"])
        assert result.exit_code == 0

    def test_search_dry_run(self, test_env):
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
