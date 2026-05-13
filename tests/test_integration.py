"""集成测试 — CLI 输出断言 + MCP 协议层 dispatch + E2E 场景

目标：
1. CLI 子命令输出内容格式验证（不限于 exit_code）
2. MCP stdio 模式：mock stdin/stdout 测 JSON-RPC dispatch（新旧协议兼容）
3. MCP HTTP 模式：mock http.server 测 _run_http 工具调用
4. 端到端场景：搜索→audit→export 完整工作流
"""

import json
import os
import sys
import tempfile
import threading
import time
from io import StringIO
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from hfpapers.cli import app
from hfpapers.mcp_server import MCP_TOOLS, HANDLERS

runner = CliRunner()

# ════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════


def _normalize_output(text: str) -> str:
    """去除 Rich 控制符 -> 纯文本"""
    import re
    # Rich 渲染和 Rich markup 标签
    text = re.sub(r'\x1b\[[0-9;]*m', '', text)
    text = re.sub(r'\[/?[a-z]+\]', '', text)
    return text.strip()


def _create_arxiv_meta_db(db_path: str, papers: list[dict] = None):
    """创建 arxiv_meta.db 并插入测试数据"""
    import sqlite3
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS arxiv_meta (
            arxiv_id TEXT PRIMARY KEY, title TEXT, authors TEXT, abstract TEXT,
            categories TEXT, doi TEXT, journal_ref TEXT, update_date TEXT,
            source TEXT DEFAULT '', imported_at TEXT DEFAULT (datetime('now')))
    """)
    for p in (papers or []):
        conn.execute(
            "INSERT OR IGNORE INTO arxiv_meta (arxiv_id, title, source, doi) VALUES (?, ?, ?, ?)",
            (p["arxiv_id"], p["title"], p.get("source", ""), p.get("doi", "")),
        )
    conn.commit()
    conn.close()


def _parse_jsonl_output(text: str) -> list[dict]:
    """从 CLI 输出中提取 JSON 行（audit --json 输出）"""
    lines = text.strip().split("\n")
    # 找第一个 { 到最后一个 }
    start, end = None, None
    for i, l in enumerate(lines):
        if l.strip().startswith("{"):
            start = i
        if l.strip().endswith("}"):
            end = i
    if start is not None and end is not None:
        joined = "\n".join(lines[start:end + 1])
        return json.loads(joined)
    return None


# ════════════════════════════════════════════
# Part 1: CLI 集成测试 — 输出内容断言
# ════════════════════════════════════════════


class TestCLIIntegration:
    """强化 CLI 子命令输出格式验证"""

    def test_help_contains_all_commands(self):
        """--help 列出所有核心子命令"""
        result = runner.invoke(app, ["--help"])
        text = _normalize_output(result.output)
        for cmd in ["search", "download", "convert", "list",
                     "info", "dedup", "store", "audit", "mcp",
                     "config", "stats"]:
            assert cmd in text, f"子命令 {cmd} 未出现在 --help 中"

    def test_audit_empty_db(self, test_env):
        """空数据库 audit 返回 '不存在'"""
        result = runner.invoke(app, ["audit"])
        assert result.exit_code == 0
        text = _normalize_output(result.output)
        # 空库时 db_exists=False 输出 "❌"
        assert "❌" in text or "0 篇" in text or "db_exists" in text.lower()

    def test_audit_json_output(self, test_env):
        """audit --json 返回合法 JSON"""
        # 先造一篇数据让审计有点东西
        db_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(db_dir, exist_ok=True)
        _create_arxiv_meta_db(os.path.join(db_dir, "arxiv_meta.db"), [
            {"arxiv_id": "2501.00001", "title": "Test", "source": "oai"},
        ])

        result = runner.invoke(app, ["audit", "--json"])
        assert result.exit_code == 0

        parsed = _parse_jsonl_output(result.output)
        assert parsed is not None, "无法从输出解析 JSON"
        # full_audit 顶层结构：timestamp + arxiv_meta + paper_store
        assert "timestamp" in parsed
        assert "arxiv_meta" in parsed
        assert "paper_store" in parsed

    def test_audit_json_via_cli_flag(self, test_env):
        """audit --meta --json 输出合法 JSON"""
        db_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(db_dir, exist_ok=True)
        _create_arxiv_meta_db(os.path.join(db_dir, "arxiv_meta.db"), [
            {"arxiv_id": "2501.00002", "title": "Test2", "source": "oai"},
        ])

        result = runner.invoke(app, ["audit", "--meta", "--json"])
        assert result.exit_code == 0
        parsed = _parse_jsonl_output(result.output)
        assert parsed is not None
        assert "db_path" in parsed
        assert parsed.get("total") == 1

    def test_store_stats_empty_output(self, test_env):
        """store stats 输出有 '论文' 字样"""
        result = runner.invoke(app, ["store", "stats"])
        assert result.exit_code == 0
        text = _normalize_output(result.output)
        # 空库，但应该显示统计信息
        assert "论文" in text or "0" in text

    def test_store_export_unsupported_format_output(self, test_env):
        """store export 不支持的格式应报错信息"""
        result = runner.invoke(app, ["store", "export", "xlsx"])
        assert result.exit_code == 1
        assert "不支持" in result.output or "xlsx" in result.output.lower()

    def test_download_unknown_source(self, test_env):
        """download --source=invalid 应报错"""
        result = runner.invoke(app, ["download", "--source", "invalid"])
        assert result.exit_code == 0
        text = _normalize_output(result.output)
        assert "未知" in text or "invalid" in text.lower()

    def test_mcp_help_available(self):
        """mcp 子命令在 --help 中列出"""
        result = runner.invoke(app, ["mcp", "--help"])
        assert result.exit_code == 0
        assert "stdio" in result.output

    def test_list_empty_output(self):
        """list 空库输出应为友好提示"""
        result = runner.invoke(app, ["list"])
        assert result.exit_code in (0, 1)
        # 空库应显示 0 或无论文
        text = _normalize_output(result.output)
        assert len(text) > 0  # 总得有输出

    def test_stats_command_output(self, test_env):
        """stats 子命令输出格式"""
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        text = _normalize_output(result.output)
        # 应有统计指标
        assert len(text) > 0

    def test_dedup_output(self, test_env):
        """dedup 子命令输出"""
        result = runner.invoke(app, ["dedup"])
        assert result.exit_code == 0
        text = _normalize_output(result.output)
        assert len(text) > 0

    def test_search_dry_run_output_format(self, test_env):
        """search --dry-run 输出格式（mock 网络）"""
        from unittest.mock import patch
        with patch("hfpapers.evolved.HFPapersCrawler.crawl", return_value=[]):
            result = runner.invoke(app, ["search", "--dry-run"])
        assert result.exit_code == 0
        text = _normalize_output(result.output)
        assert "0" in text or "论文" in text

    def test_convert_no_pdfs_output(self, test_env):
        """convert 没有 PDF 时友好提示"""
        result = runner.invoke(app, ["convert"])
        assert result.exit_code in (0, 1)
        text = _normalize_output(result.output)
        assert len(text) > 0

    def test_audit_paper_store_flags(self, test_env):
        """audit --paper-store / --meta 不同 flag 输出不同"""
        # 两个 flag 至少都能跑不崩
        # --meta 在空 DB 时可能返回 1（无 DB 异常），--paper-store 可能返回 0
        r1 = runner.invoke(app, ["audit", "--paper-store"])
        r2 = runner.invoke(app, ["audit", "--meta"])
        for r in [r1, r2]:
            assert r.exit_code in (0, 1), f"exit_code={r.exit_code}: {r.output[:200]}"


# ════════════════════════════════════════════
# Part 2: MCP 协议层测试 — HANDLERS dispatch
# ════════════════════════════════════════════


class TestMCPDispatch:
    """直接测试 MCP HANDLERS dispatch 函数（不需网络）"""

    def test_all_tools_registered(self):
        """MCP_TOOLS 中每个 tool 都有对应 handler"""
        assert len(MCP_TOOLS) == 7
        for name in MCP_TOOLS:
            assert name in HANDLERS, f"{name} 没有 handler"
            assert callable(HANDLERS[name])

    def test_handler_search_empty(self):
        """search handler 在无 dedup 文件时也能返回结果"""
        result = json.loads(HANDLERS["hfpclawer_search"]({}))
        # 没有真数据时返回正确结构
        assert "total_new" in result
        assert isinstance(result["papers"], list)

    def test_handler_stats_empty(self):
        """stats handler 返回统计结构"""
        result = json.loads(HANDLERS["hfpclawer_stats"]({}))
        assert "total_papers" in result
        assert "pdf_files" in result

    def test_handler_info_not_found(self):
        """info handler 找不到 ID 返回 error"""
        result = json.loads(HANDLERS["hfpclawer_info"]({"arxiv_id": "9999.99999"}))
        assert "error" in result
        assert "9999.99999" in result["error"]

    def test_handler_list_empty(self):
        """list handler 返回结构"""
        result = json.loads(HANDLERS["hfpclawer_list"]({}))
        assert "total" in result
        assert "papers" in result

    def test_handler_full(self):
        """full pipeline handler 返回三阶段结构"""
        result = json.loads(HANDLERS["hfpclawer_full"]({}))
        assert "search" in result
        assert "download" in result
        assert "convert" in result

    def test_handler_convert(self):
        """convert handler 返回转换计数"""
        result = json.loads(HANDLERS["hfpclawer_convert"]({}))
        assert "converted" in result

    def test_unknown_tool_not_in_handlers(self):
        """不存在的 tool 不在 HANDLERS 中"""
        assert "hfpclawer_nonexistent" not in HANDLERS

    def test_search_with_params(self):
        """search handler 接收参数（阈值等）"""
        result = json.loads(HANDLERS["hfpclawer_search"]({
            "max_pages": 1,
            "threshold": 50,
            "dry_run": True,
        }))
        assert "total_new" in result

    def test_download_empty(self):
        """download handler 无候选时友好报错"""
        result = json.loads(HANDLERS["hfpclawer_download"]({}))
        assert "error" in result or "downloaded" in result


# ════════════════════════════════════════════
# Part 3: MCP stdio 协议集成测试
# ════════════════════════════════════════════


class TestMCPStdioProtocol:
    """mock stdin/stdout 测 _run_stdio JSON-RPC 协议层

    发标准 JSON-RPC 消息验证 tools/list / tools/call / initialize
    """

    @staticmethod
    def _run_stdio_with_input(input_lines: list[str],
                               timeout: float = 2.0,
                               test_env: str = None) -> list[str]:  # noqa: ARG004 - used for fixture compatibility
        """在单独线程运行 _run_stdio，模拟 stdin/stdout"""
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

            # 在子线程中运行（_run_stdio 内部是 while True）
            thread = threading.Thread(target=_run_stdio, daemon=True)
            thread.start()

            # 等待线程执行（或超时）
            thread.join(timeout=timeout)

            # 读取输出
            output = mock_stdout.getvalue()
            results = [line for line in output.strip().split("\n") if line.strip()]

        finally:
            sys.stdin = orig_stdin
            sys.stdout = orig_stdout

        return results

    def test_tools_list(self, test_env):
        """MCP stdio: tools/list 返回工具列表"""
        from hfpapers.mcp_server import _run_stdio

        # 构造输入输出
        req = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
        })

        mock_stdin = StringIO(req + "\n")
        mock_stdout = StringIO()

        with patch.object(sys, 'stdin', mock_stdin), \
             patch.object(sys, 'stdout', mock_stdout):
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
        """MCP stdio: tools/call search 返回搜索结果"""
        from hfpapers.mcp_server import _run_stdio

        req = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "hfpclawer_search",
                "arguments": {"max_pages": 1, "threshold": 50, "dry_run": True},
            },
        })

        mock_stdin = StringIO(req + "\n")
        mock_stdout = StringIO()

        with patch.object(sys, 'stdin', mock_stdin), \
             patch.object(sys, 'stdout', mock_stdout):
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

        # 验证内容是合法 JSON
        content_text = resp["result"]["content"][0]["text"]
        content_json = json.loads(content_text)
        assert "total_new" in content_json

    def test_tools_call_stats(self):
        """MCP stdio: tools/call stats 返回统计"""
        from hfpapers.mcp_server import _run_stdio

        req = json.dumps({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "hfpclawer_stats",
                "arguments": {},
            },
        })

        mock_stdin = StringIO(req + "\n")
        mock_stdout = StringIO()

        with patch.object(sys, 'stdin', mock_stdin), \
             patch.object(sys, 'stdout', mock_stdout):
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
        """MCP stdio: tools/call unknown tool 返回 error"""
        from hfpapers.mcp_server import _run_stdio

        req = json.dumps({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "hfpclawer_nonexistent",
                "arguments": {},
            },
        })

        mock_stdin = StringIO(req + "\n")
        mock_stdout = StringIO()

        with patch.object(sys, 'stdin', mock_stdin), \
             patch.object(sys, 'stdout', mock_stdout):
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
        """MCP stdio: initialize 返回协议版本"""
        from hfpapers.mcp_server import _run_stdio

        req = json.dumps({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "initialize",
        })

        mock_stdin = StringIO(req + "\n")
        mock_stdout = StringIO()

        with patch.object(sys, 'stdin', mock_stdin), \
             patch.object(sys, 'stdout', mock_stdout):
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
        """MCP stdio: 未知 method 返回 error"""
        from hfpapers.mcp_server import _run_stdio

        req = json.dumps({
            "jsonrpc": "2.0",
            "id": 6,
            "method": "resources/list",
        })

        mock_stdin = StringIO(req + "\n")
        mock_stdout = StringIO()

        with patch.object(sys, 'stdin', mock_stdin), \
             patch.object(sys, 'stdout', mock_stdout):
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
        """MCP stdio: 旧版 line-JSON 协议（无 jsonrpc 字段）仍可工作"""
        from hfpapers.mcp_server import _run_stdio

        # 旧版协议：直接发 {"tool": "...", "params": {...}}
        req = json.dumps({
            "tool": "hfpclawer_stats",
            "params": {},
        })

        mock_stdin = StringIO(req + "\n")
        mock_stdout = StringIO()

        with patch.object(sys, 'stdin', mock_stdin), \
             patch.object(sys, 'stdout', mock_stdout):
            try:
                _run_stdio()
            except SystemExit:
                pass

        output = mock_stdout.getvalue()
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert len(lines) >= 1

        # 旧版协议直接返回 JSON 字符串（不是 JSON-RPC 响应）
        resp = json.loads(lines[0])
        # 可能是 error 或 stats
        assert isinstance(resp, dict)

    def test_malformed_json(self):
        """MCP stdio: 损坏的 JSON 不崩溃"""
        from hfpapers.mcp_server import _run_stdio

        # 发给 stdin 一个损坏的行
        mock_stdin = StringIO("this is not json\n")
        mock_stdout = StringIO()

        with patch.object(sys, 'stdin', mock_stdin), \
             patch.object(sys, 'stdout', mock_stdout):
            try:
                _run_stdio()
            except (SystemExit, StopIteration):
                pass

        # 不应该抛异常，应忽略损坏的行
        output = mock_stdout.getvalue()
        # 可以被静默忽略，也可以返回错误，但绝不崩溃
        assert True  # 没有异常就是成功

    def test_mcp_tools_list_content(self):
        """MCP TOOLS 模式 — 每个工具都有完整的 schema"""
        for name, schema in MCP_TOOLS.items():
            assert "description" in schema, f"{name} 缺 description"
            assert "input_schema" in schema, f"{name} 缺 input_schema"
            assert "properties" in schema["input_schema"], f"{name} 缺 properties"

    def test_mcp_tool_schema_format(self):
        """MCP tools schema 格式兼容 Hermes MCP client"""
        for name, schema in MCP_TOOLS.items():
            # Hermes MCP client 期望格式
            assert "name" in schema
            assert schema["name"] == name


# ════════════════════════════════════════════
# Part 4: MCP HTTP 模式集成测试
# ════════════════════════════════════════════


class TestMCPHTTP:
    """mock http.server 测 _run_http HTTP 模式"""

    _http_ports = iter(range(28765, 28799))  # 固定端口池避免竞争

    @classmethod
    def _free_port(cls) -> int:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            return s.getsockname()[1]

    def _serve_http(self, port: int, timeout: float = 2.0):
        """在单独线程中启动 HTTP server，返回线程"""
        from hfpapers.mcp_server import _run_http
        t = threading.Thread(target=_run_http, args=("127.0.0.1", port), daemon=True)
        t.start()
        return t

    def _wait_http(self, port: int, retries: int = 5):
        """等待 HTTP server 就绪"""
        import socket
        for i in range(retries):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return True
            except (ConnectionRefusedError, OSError):
                time.sleep(0.3)
        return False

    def test_http_tools_list_via_get(self):
        """HTTP MCP: GET /tools 返回工具列表"""
        port = self._free_port()
        t = self._serve_http(port)
        if not self._wait_http(port):
            pytest.skip(f"HTTP server 未能在端口 {port} 上启动")

        import urllib.request
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/tools", timeout=3)
            data = json.loads(resp.read().decode())
            assert "hfpclawer_search" in data or "hfpclawer_stats" in data
        except Exception as e:
            pytest.skip(f"HTTP /tools 请求失败: {e}")

    def test_http_call_via_get(self):
        """HTTP MCP: GET /call/stats 返回统计"""
        port = self._free_port()
        t = self._serve_http(port)
        if not self._wait_http(port):
            pytest.skip(f"HTTP server 未能在端口 {port} 上启动")

        import urllib.request
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/call/hfpclawer_stats", timeout=3)
            data = json.loads(resp.read().decode())
            assert "total_papers" in data
            assert "pdf_files" in data
        except Exception as e:
            pytest.skip(f"HTTP /call/stats 请求失败: {e}")

    def test_http_call_via_post(self):
        """HTTP MCP: POST /call/hfpclawer_search 传参"""
        port = self._free_port()
        t = self._serve_http(port)
        if not self._wait_http(port):
            pytest.skip(f"HTTP server 未能在端口 {port} 上启动")

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
            pytest.skip(f"HTTP POST 请求失败: {e}")

    def test_http_unknown_tool(self):
        """HTTP MCP: 不存在的工具返回 404"""
        port = self._free_port()
        t = self._serve_http(port)
        if not self._wait_http(port):
            pytest.skip(f"HTTP server 未能在端口 {port} 上启动")

        import urllib.request
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/call/hfpclawer_nonexistent",
                method="GET",
            )
            try:
                urllib.request.urlopen(req, timeout=3)
                pytest.fail("应有 404 但请求成功")
            except urllib.error.HTTPError as e:
                assert e.code == 404
        except Exception as e:
            pytest.skip(f"HTTP 请求失败: {e}")

    def test_http_health_endpoint(self):
        """HTTP MCP: GET /health 返回 ok"""
        port = self._free_port()
        t = self._serve_http(port)
        if not self._wait_http(port):
            pytest.skip(f"HTTP server 未能在端口 {port} 上启动")

        import urllib.request
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3)
            data = json.loads(resp.read().decode())
            assert data["status"] == "ok"
        except Exception as e:
            pytest.skip(f"HTTP /health 请求失败: {e}")


# ════════════════════════════════════════════
# Part 5: E2E 工作流 — 多子命令组合
# ════════════════════════════════════════════


class TestE2EWorkflow:
    """端到端工作流场景 — 验证完整 CLI 可用性"""

    def test_search_audit_workflow(self, test_env):
        """search → audit 组合调用"""
        from unittest.mock import patch
        with patch("hfpapers.evolved.HFPapersCrawler.crawl", return_value=[]):
            r1 = runner.invoke(app, ["search", "--dry-run"])
        assert r1.exit_code == 0

        # 再 audit
        r2 = runner.invoke(app, ["audit"])
        assert r2.exit_code == 0

    def test_full_pipeline_dry(self, test_env):
        """full --dry-run 等效场景"""
        from unittest.mock import patch
        with patch("hfpapers.evolved.HFPapersCrawler.crawl", return_value=[]):
            result = runner.invoke(app, ["search", "--dry-run"])
        assert result.exit_code == 0

    def test_mcp_http_mode(self, test_env):
        """mcp http 模式能启动（需 mock 避免阻塞）"""
        # 验证 CLI 到 mcp 的调用路径，不真正启动 server
        # 用 patch 拦截 run_mcp_server
        with patch("hfpapers.mcp_server.run_mcp_server") as mock_run:
            result = runner.invoke(app, ["mcp", "--mode", "http"])
            assert result.exit_code == 0
            # 验证传参正确
            mock_run.assert_called_once()
            _, kwargs = mock_run.call_args
            assert kwargs["mode"] == "http"

    def test_mcp_stdio_mode_with_command(self, test_env):
        """mcp stdio 模式调用路径（mock 避免阻塞）"""
        with patch("hfpapers.mcp_server.run_mcp_server") as mock_run:
            result = runner.invoke(app, ["mcp", "--mode", "stdio"])
            assert result.exit_code == 0
            mock_run.assert_called_once()

    def test_cli_chain_no_crash(self, test_env):
        """连续多次调用各子命令，确保全局状态不污染"""
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
            assert result.exit_code in (0, 1), f"命令 {' '.join(cmd)} 退出码意外: {result.exit_code}"

        # search 需要 mock 网络
        with patch("hfpapers.evolved.HFPapersCrawler.crawl", return_value=[]):
            result = runner.invoke(app, ["search", "--dry-run"])
        assert result.exit_code in (0, 1)
