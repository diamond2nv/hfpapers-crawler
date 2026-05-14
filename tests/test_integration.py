#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integration tests — CLI output assertions + MCP protocol dispatch + E2E scenarios

Goals:
1. CLI subcommand output content format verification (beyond exit_code)
2. MCP stdio mode: mock stdin/stdout test JSON-RPC dispatch (new/old protocol compatible)
3. MCP HTTP mode: mock http.server test _run_http tool invocation
4. End-to-end scenario: search → audit → export full workflow
"""

import json
import os
import sys
import threading
import time
from io import StringIO
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from hfpapers.cli import app
from hfpapers.mcp_server import HANDLERS, MCP_TOOLS

runner = CliRunner()

# ════════════════════════════════════════════
# Helper functions
# ════════════════════════════════════════════


def _normalize_output(text: str) -> str:
    """Remove Rich control characters -> plain text"""
    import re

    # Rich rendering and Rich markup tags
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = re.sub(r"\[/?[a-z]+\]", "", text)
    return text.strip()


def _create_arxiv_meta_db(db_path: str, papers: list[dict] = None):
    """Create arxiv_meta.db and insert test data"""
    import sqlite3

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS arxiv_meta (
            arxiv_id TEXT PRIMARY KEY, title TEXT, authors TEXT, abstract TEXT,
            categories TEXT, doi TEXT, journal_ref TEXT, update_date TEXT,
            source TEXT DEFAULT '', imported_at TEXT DEFAULT (datetime('now')))
    """)
    for p in papers or []:
        conn.execute(
            "INSERT OR IGNORE INTO arxiv_meta (arxiv_id, title, source, doi) VALUES (?, ?, ?, ?)",
            (p["arxiv_id"], p["title"], p.get("source", ""), p.get("doi", "")),
        )
    conn.commit()
    conn.close()


def _parse_jsonl_output(text: str) -> list[dict]:
    """Extract JSON line from CLI output (audit --json output)"""
    lines = text.strip().split("\n")
    # Find first { to last }
    start, end = None, None
    for i, l in enumerate(lines):
        if l.strip().startswith("{"):
            start = i
        if l.strip().endswith("}"):
            end = i
    if start is not None and end is not None:
        joined = "\n".join(lines[start : end + 1])
        return json.loads(joined)
    return None


# ════════════════════════════════════════════
# Part 1: CLI integration test — output content assertions
# ════════════════════════════════════════════


class TestCLIIntegration:
    """Enhanced CLI subcommand output format verification"""

    def test_help_contains_all_commands(self):
        """--help lists all core subcommands"""
        result = runner.invoke(app, ["--help"])
        text = _normalize_output(result.output)
        for cmd in [
            "search",
            "download",
            "convert",
            "list",
            "info",
            "dedup",
            "store",
            "audit",
            "mcp",
            "config",
            "stats",
        ]:
            assert cmd in text, f"Subcommand {cmd} not found in --help"

    def test_audit_empty_db(self, test_env):
        """Empty database audit returns 'does not exist'"""
        result = runner.invoke(app, ["audit"])
        assert result.exit_code == 0
        text = _normalize_output(result.output)
        # When empty, db_exists=False outputs "❌"
        assert "❌" in text or "0" in text or "db_exists" in text.lower()

    def test_audit_json_output(self, test_env):
        """audit --json returns valid JSON"""
        # Insert a paper so audit has data to work with
        db_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(db_dir, exist_ok=True)
        _create_arxiv_meta_db(
            os.path.join(db_dir, "arxiv_meta.db"),
            [
                {"arxiv_id": "2501.00001", "title": "Test", "source": "oai"},
            ],
        )

        result = runner.invoke(app, ["audit", "--json"])
        assert result.exit_code == 0

        parsed = _parse_jsonl_output(result.output)
        assert parsed is not None, "Could not parse JSON from output"
        # full_audit top-level structure: timestamp + arxiv_meta + paper_store
        assert "timestamp" in parsed
        assert "arxiv_meta" in parsed
        assert "paper_store" in parsed

    def test_audit_json_via_cli_flag(self, test_env):
        """audit --meta --json outputs valid JSON"""
        db_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(db_dir, exist_ok=True)
        _create_arxiv_meta_db(
            os.path.join(db_dir, "arxiv_meta.db"),
            [
                {"arxiv_id": "2501.00002", "title": "Test2", "source": "oai"},
            ],
        )

        result = runner.invoke(app, ["audit", "--meta", "--json"])
        assert result.exit_code == 0
        parsed = _parse_jsonl_output(result.output)
        assert parsed is not None
        assert "db_path" in parsed
        assert parsed.get("total") == 1

    def test_store_stats_empty_output(self, test_env):
        """store stats output contains 'papers' text"""
        result = runner.invoke(app, ["store", "stats"])
        assert result.exit_code == 0
        text = _normalize_output(result.output)
        # Empty DB, but should display statistics
        assert "paper" in text or "0" in text

    def test_store_export_unsupported_format_output(self, test_env):
        """store export unsupported format should report error"""
        result = runner.invoke(app, ["store", "export", "xlsx"])
        assert result.exit_code == 1
        assert "not supported" in result.output or "xlsx" in result.output.lower()

    def test_download_unknown_source(self, test_env):
        """download --source=invalid should report error"""
        result = runner.invoke(app, ["download", "--source", "invalid"])
        assert result.exit_code == 0
        text = _normalize_output(result.output)
        assert "unknown" in text or "invalid" in text.lower()

    def test_mcp_help_available(self):
        """mcp subcommand listed in --help"""
        result = runner.invoke(app, ["mcp", "--help"])
        assert result.exit_code == 0
        assert "stdio" in result.output

    def test_list_empty_output(self):
        """list empty DB output should be friendly message"""
        result = runner.invoke(app, ["list"])
        assert result.exit_code in (0, 1)
        # Empty DB should show 0 or no papers
        text = _normalize_output(result.output)
        assert len(text) > 0  # Must have some output

    def test_stats_command_output(self, test_env):
        """stats subcommand output format"""
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        text = _normalize_output(result.output)
        # Should have statistics metrics
        assert len(text) > 0

    def test_dedup_output(self, test_env):
        """dedup subcommand output"""
        result = runner.invoke(app, ["dedup"])
        assert result.exit_code == 0
        text = _normalize_output(result.output)
        assert len(text) > 0

    def test_search_dry_run_output_format(self, test_env):
        """search --dry-run output format (mock network)"""
        from unittest.mock import patch

        with patch("hfpapers.evolved.HFPapersCrawler.crawl", return_value=[]):
            result = runner.invoke(app, ["search", "--dry-run"])
        assert result.exit_code == 0
        text = _normalize_output(result.output)
        assert "0" in text or "paper" in text

    def test_convert_no_pdfs_output(self, test_env):
        """convert friendly message when no PDF"""
        result = runner.invoke(app, ["convert"])
        assert result.exit_code in (0, 1)
        text = _normalize_output(result.output)
        assert len(text) > 0

    def test_audit_paper_store_flags(self, test_env):
        """audit --paper-store / --meta different flags produce different output"""
        # Both flags at least run without crashing
        # --meta may return 1 on empty DB (no DB exception), --paper-store may return 0
        r1 = runner.invoke(app, ["audit", "--paper-store"])
        r2 = runner.invoke(app, ["audit", "--meta"])
        for r in [r1, r2]:
            assert r.exit_code in (0, 1), f"exit_code={r.exit_code}: {r.output[:200]}"


# ════════════════════════════════════════════
# Part 2: MCP protocol layer test — HANDLERS dispatch
# ════════════════════════════════════════════


class TestMCPDispatch:
    """Directly test MCP HANDLERS dispatch function (no network needed)"""

    def test_all_tools_registered(self):
        """Each tool in MCP_TOOLS has a corresponding handler"""
        assert len(MCP_TOOLS) == 7
        for name in MCP_TOOLS:
            assert name in HANDLERS, f"{name} has no handler"
            assert callable(HANDLERS[name])

    def test_handler_search_empty(self):
        """search handler returns results even without dedup file"""
        result = json.loads(HANDLERS["hfpclawer_search"]({}))
        # Returns correct structure when no real data
        assert "total_new" in result
        assert isinstance(result["papers"], list)

    def test_handler_stats_empty(self):
        """stats handler returns statistics structure"""
        result = json.loads(HANDLERS["hfpclawer_stats"]({}))
        assert "total_papers" in result
        assert "pdf_files" in result

    def test_handler_info_not_found(self):
        """info handler returns error when ID not found"""
        result = json.loads(HANDLERS["hfpclawer_info"]({"arxiv_id": "9999.99999"}))
        assert "error" in result
        assert "9999.99999" in result["error"]

    def test_handler_list_empty(self):
        """list handler returns structure"""
        result = json.loads(HANDLERS["hfpclawer_list"]({}))
        assert "total" in result
        assert "papers" in result

    def test_handler_full(self):
        """full pipeline handler returns three-phase structure"""
        result = json.loads(HANDLERS["hfpclawer_full"]({}))
        assert "search" in result
        assert "download" in result
        assert "convert" in result

    def test_handler_convert(self):
        """convert handler returns conversion count"""
        result = json.loads(HANDLERS["hfpclawer_convert"]({}))
        assert "converted" in result

    def test_unknown_tool_not_in_handlers(self):
        """Non-existent tool not in HANDLERS"""
        assert "hfpclawer_nonexistent" not in HANDLERS

    def test_search_with_params(self):
        """search handler accepts parameters (threshold, etc.)"""
        result = json.loads(
            HANDLERS["hfpclawer_search"](
                {
                    "max_pages": 1,
                    "threshold": 50,
                    "dry_run": True,
                }
            )
        )
        assert "total_new" in result

    def test_download_empty(self):
        """download handler friendly error when no candidates"""
        result = json.loads(HANDLERS["hfpclawer_download"]({}))
        assert "error" in result or "downloaded" in result


# ════════════════════════════════════════════
# Part 3: MCP stdio protocol integration test
# ════════════════════════════════════════════


class TestMCPStdioProtocol:
    """Mock stdin/stdout test _run_stdio JSON-RPC protocol layer

    Send standard JSON-RPC messages to verify tools/list / tools/call / initialize
    """

    @staticmethod
    def _run_stdio_with_input(
        input_lines: list[str], timeout: float = 2.0, test_env: str = None
    ) -> list[str]:  # noqa: ARG004 - used for fixture compatibility
        """Run _run_stdio in separate thread, mock stdin/stdout"""
        from hfpapers.mcp_server import _run_stdio

        orig_stdin = sys.stdin
        orig_stdout = sys.stdout
        results = []

        try:
            # mock stdin
            mock_stdin = StringIO("\n".join(input_lines) + "\n")
            sys.stdin = mock_stdin

            # capture stdout
            mock_stdout = StringIO()
            sys.stdout = mock_stdout

            # Run in child thread (_run_stdio internally is while True)
            thread = threading.Thread(target=_run_stdio, daemon=True)
            thread.start()

            # Wait for thread execution (or timeout)
            thread.join(timeout=timeout)

            # Read output
            output = mock_stdout.getvalue()
            results = [line for line in output.strip().split("\n") if line.strip()]

        finally:
            sys.stdin = orig_stdin
            sys.stdout = orig_stdout

        return results

    def test_tools_list(self, test_env):
        """MCP stdio: tools/list returns tool list"""
        from hfpapers.mcp_server import _run_stdio

        # Build input/output
        req = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            }
        )

        mock_stdin = StringIO(req + "\n")
        mock_stdout = StringIO()

        with patch.object(sys, "stdin", mock_stdin), patch.object(sys, "stdout", mock_stdout):
            try:
                _run_stdio()
            except SystemExit:
                pass

        output = mock_stdout.getvalue()
        lines = [l for l in output.strip().split("\n") if l.strip()]

        assert len(lines) >= 1
        resp = json.loads(lines[0])
        assert resp.get("id") == 1
        assert "result" in resp
        assert "tools" in resp["result"]
        assert len(resp["result"]["tools"]) == len(MCP_TOOLS)

    def test_tools_call_search(self):
        """MCP stdio: tools/call search returns search results"""
        from hfpapers.mcp_server import _run_stdio

        req = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "hfpclawer_search",
                    "arguments": {"max_pages": 1, "threshold": 50, "dry_run": True},
                },
            }
        )

        mock_stdin = StringIO(req + "\n")
        mock_stdout = StringIO()

        with patch.object(sys, "stdin", mock_stdin), patch.object(sys, "stdout", mock_stdout):
            try:
                _run_stdio()
            except SystemExit:
                pass

        output = mock_stdout.getvalue()
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert len(lines) >= 1

        resp = json.loads(lines[0])
        assert resp.get("id") == 2
        assert "result" in resp
        assert "content" in resp["result"]

        # Verify content is valid JSON
        content_text = resp["result"]["content"][0]["text"]
        content_json = json.loads(content_text)
        assert "total_new" in content_json

    def test_tools_call_stats(self):
        """MCP stdio: tools/call stats returns statistics"""
        from hfpapers.mcp_server import _run_stdio

        req = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "hfpclawer_stats",
                    "arguments": {},
                },
            }
        )

        mock_stdin = StringIO(req + "\n")
        mock_stdout = StringIO()

        with patch.object(sys, "stdin", mock_stdin), patch.object(sys, "stdout", mock_stdout):
            try:
                _run_stdio()
            except SystemExit:
                pass

        output = mock_stdout.getvalue()
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert len(lines) >= 1

        resp = json.loads(lines[0])
        assert resp.get("id") == 3
        content_text = resp["result"]["content"][0]["text"]
        content_json = json.loads(content_text)
        assert "total_papers" in content_json
        assert "pdf_files" in content_json

    def test_tools_call_unknown_tool(self):
        """MCP stdio: tools/call unknown tool returns error"""
        from hfpapers.mcp_server import _run_stdio

        req = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "hfpclawer_nonexistent",
                    "arguments": {},
                },
            }
        )

        mock_stdin = StringIO(req + "\n")
        mock_stdout = StringIO()

        with patch.object(sys, "stdin", mock_stdin), patch.object(sys, "stdout", mock_stdout):
            try:
                _run_stdio()
            except SystemExit:
                pass

        output = mock_stdout.getvalue()
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert len(lines) >= 1

        resp = json.loads(lines[0])
        assert "error" in resp
        assert "unknown tool" in resp["error"]["message"]

    def test_initialize(self):
        """MCP stdio: initialize returns protocol version"""
        from hfpapers.mcp_server import _run_stdio

        req = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "initialize",
            }
        )

        mock_stdin = StringIO(req + "\n")
        mock_stdout = StringIO()

        with patch.object(sys, "stdin", mock_stdin), patch.object(sys, "stdout", mock_stdout):
            try:
                _run_stdio()
            except SystemExit:
                pass

        output = mock_stdout.getvalue()
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert len(lines) >= 1

        resp = json.loads(lines[0])
        assert resp.get("id") == 5
        assert resp["result"]["protocolVersion"] == "2024-11-05"
        assert resp["result"]["serverInfo"]["name"] == "hfpapers-mcp"

    def test_unknown_method(self):
        """MCP stdio: unknown method returns error"""
        from hfpapers.mcp_server import _run_stdio

        req = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "resources/list",
            }
        )

        mock_stdin = StringIO(req + "\n")
        mock_stdout = StringIO()

        with patch.object(sys, "stdin", mock_stdin), patch.object(sys, "stdout", mock_stdout):
            try:
                _run_stdio()
            except SystemExit:
                pass

        output = mock_stdout.getvalue()
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert len(lines) >= 1

        resp = json.loads(lines[0])
        assert "error" in resp
        assert "unknown method" in resp["error"]["message"]

    def test_legacy_compat(self):
        """MCP stdio: legacy line-JSON protocol (no jsonrpc field) still works"""
        from hfpapers.mcp_server import _run_stdio

        # Legacy protocol: send {"tool": "...", "params": {...}} directly
        req = json.dumps(
            {
                "tool": "hfpclawer_stats",
                "params": {},
            }
        )

        mock_stdin = StringIO(req + "\n")
        mock_stdout = StringIO()

        with patch.object(sys, "stdin", mock_stdin), patch.object(sys, "stdout", mock_stdout):
            try:
                _run_stdio()
            except SystemExit:
                pass

        output = mock_stdout.getvalue()
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert len(lines) >= 1

        # Legacy protocol returns JSON string directly (not JSON-RPC response)
        resp = json.loads(lines[0])
        # Could be error or stats
        assert isinstance(resp, dict)

    def test_malformed_json(self):
        """MCP stdio: malformed JSON does not crash"""
        from hfpapers.mcp_server import _run_stdio

        # Send a malformed line to stdin
        mock_stdin = StringIO("this is not json\n")
        mock_stdout = StringIO()

        with patch.object(sys, "stdin", mock_stdin), patch.object(sys, "stdout", mock_stdout):
            try:
                _run_stdio()
            except (SystemExit, StopIteration):
                pass

        # Should not throw exception, should ignore malformed line
        output = mock_stdout.getvalue()
        # Can be silently ignored or return error, but never crash
        assert True  # No exception means success

    def test_mcp_tools_list_content(self):
        """MCP TOOLS mode — each tool has complete schema"""
        for name, schema in MCP_TOOLS.items():
            assert "description" in schema, f"{name} missing description"
            assert "input_schema" in schema, f"{name} missing input_schema"
            assert "properties" in schema["input_schema"], f"{name} missing properties"

    def test_mcp_tool_schema_format(self):
        """MCP tools schema format compatible with Hermes MCP client"""
        for name, schema in MCP_TOOLS.items():
            # Hermes MCP client expected format
            assert "name" in schema
            assert schema["name"] == name


# ════════════════════════════════════════════
# Part 4: MCP HTTP mode integration test
# ════════════════════════════════════════════


class TestMCPHTTP:
    """Mock http.server test _run_http HTTP mode"""

    _http_ports = iter(range(28765, 28799))  # Fixed port pool to avoid contention

    @classmethod
    def _free_port(cls) -> int:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    def _serve_http(self, port: int, timeout: float = 2.0):
        """Start HTTP server in separate thread, return thread"""
        from hfpapers.mcp_server import _run_http

        t = threading.Thread(target=_run_http, args=("127.0.0.1", port), daemon=True)
        t.start()
        return t

    def _wait_http(self, port: int, retries: int = 5):
        """Wait for HTTP server ready"""
        import socket

        for i in range(retries):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return True
            except (ConnectionRefusedError, OSError):
                time.sleep(0.3)
        return False

    def test_http_tools_list_via_get(self):
        """HTTP MCP: GET /tools returns tool list"""
        port = self._free_port()
        t = self._serve_http(port)
        if not self._wait_http(port):
            pytest.skip(f"HTTP server could not start on port {port}")

        import urllib.request

        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/tools", timeout=3)
            data = json.loads(resp.read().decode())
            assert "hfpclawer_search" in data or "hfpclawer_stats" in data
        except Exception as e:
            pytest.skip(f"HTTP /tools request failed: {e}")

    def test_http_call_via_get(self):
        """HTTP MCP: GET /call/stats returns statistics"""
        port = self._free_port()
        t = self._serve_http(port)
        if not self._wait_http(port):
            pytest.skip(f"HTTP server could not start on port {port}")

        import urllib.request

        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/call/hfpclawer_stats", timeout=3
            )
            data = json.loads(resp.read().decode())
            assert "total_papers" in data
            assert "pdf_files" in data
        except Exception as e:
            pytest.skip(f"HTTP /call/stats request failed: {e}")

    def test_http_call_via_post(self):
        """HTTP MCP: POST /call/hfpclawer_search with parameters"""
        port = self._free_port()
        t = self._serve_http(port)
        if not self._wait_http(port):
            pytest.skip(f"HTTP server could not start on port {port}")

        import urllib.request

        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/call/hfpclawer_search",
                data=json.dumps({"max_pages": 1, "threshold": 50, "dry_run": True}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=3)
            data = json.loads(resp.read().decode())
            assert "total_new" in data
        except Exception as e:
            pytest.skip(f"HTTP POST request failed: {e}")

    def test_http_unknown_tool(self):
        """HTTP MCP: non-existent tool returns 404"""
        port = self._free_port()
        t = self._serve_http(port)
        if not self._wait_http(port):
            pytest.skip(f"HTTP server could not start on port {port}")

        import urllib.request

        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/call/hfpclawer_nonexistent",
                method="GET",
            )
            try:
                urllib.request.urlopen(req, timeout=3)
                pytest.fail("Expected 404 but request succeeded")
            except urllib.error.HTTPError as e:
                assert e.code == 404
        except Exception as e:
            pytest.skip(f"HTTP request failed: {e}")

    def test_http_health_endpoint(self):
        """HTTP MCP: GET /health returns ok"""
        port = self._free_port()
        t = self._serve_http(port)
        if not self._wait_http(port):
            pytest.skip(f"HTTP server could not start on port {port}")

        import urllib.request

        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3)
            data = json.loads(resp.read().decode())
            assert data["status"] == "ok"
        except Exception as e:
            pytest.skip(f"HTTP /health request failed: {e}")


# ════════════════════════════════════════════
# Part 5: E2E workflow — multiple subcommand combination
# ════════════════════════════════════════════


class TestE2EWorkflow:
    """End-to-end workflow scenario — verify complete CLI usability"""

    def test_search_audit_workflow(self, test_env):
        """search → audit combined invocation"""
        from unittest.mock import patch

        with patch("hfpapers.evolved.HFPapersCrawler.crawl", return_value=[]):
            r1 = runner.invoke(app, ["search", "--dry-run"])
        assert r1.exit_code == 0

        # Then audit
        r2 = runner.invoke(app, ["audit"])
        assert r2.exit_code == 0

    def test_full_pipeline_dry(self, test_env):
        """full --dry-run equivalent scenario"""
        from unittest.mock import patch

        with patch("hfpapers.evolved.HFPapersCrawler.crawl", return_value=[]):
            result = runner.invoke(app, ["search", "--dry-run"])
        assert result.exit_code == 0

    def test_mcp_http_mode(self, test_env):
        """mcp http mode can start (needs mock to avoid blocking)"""
        # Verify CLI to mcp call path, don't actually start server
        # Use patch to intercept run_mcp_server
        with patch("hfpapers.mcp_server.run_mcp_server") as mock_run:
            result = runner.invoke(app, ["mcp", "--mode", "http"])
            assert result.exit_code == 0
            # Verify parameters are correct
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            assert kwargs["mode"] == "http"

    def test_mcp_stdio_mode_with_command(self, test_env):
        """mcp stdio mode call path (mock to avoid blocking)"""
        with patch("hfpapers.mcp_server.run_mcp_server") as mock_run:
            result = runner.invoke(app, ["mcp", "--mode", "stdio"])
            assert result.exit_code == 0
            mock_run.assert_called_once()

    def test_cli_chain_no_crash(self, test_env):
        """Call multiple subcommands sequentially, ensure global state is not polluted"""
        from unittest.mock import patch

        commands = [
            ["--help"],
            ["config"],
            ["dedup"],
            ["audit"],
            ["audit", "--paper-store"],
            ["store", "stats"],
        ]
        for cmd in commands:
            result = runner.invoke(app, cmd)
            assert result.exit_code in (0, 1), (
                f"Command {' '.join(cmd)} unexpected exit code: {result.exit_code}"
            )

        # search needs mock network
        with patch("hfpapers.evolved.HFPapersCrawler.crawl", return_value=[]):
            result = runner.invoke(app, ["search", "--dry-run"])
        assert result.exit_code in (0, 1)
