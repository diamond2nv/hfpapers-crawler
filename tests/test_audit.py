"""测试审计模块"""

import json
import os
import sqlite3
import tempfile

from hfpapers.config import load_config
from hfpapers.paper_store import get_store, ensure_paper

from typer.testing import CliRunner
from hfpapers.cli import app

runner = CliRunner()


class TestAudit:
    def test_audit_empty_db(self, test_env):
        """空数据库的审计报告"""
        from hfpclawer.audit import run_audit

        # test_env 的 config.yaml 配了 paths.data_dir, 但没有 db.path
        # paper_store 用 data/papers.db, arxiv_meta 也用 data/arxiv_meta.db
        # audit 默认查 arxiv_meta.db — 需要确保它存在
        db_path = os.path.join(os.getcwd(), "data", "arxiv_meta.db")
        os.makedirs(os.path.join(os.getcwd(), "data"), exist_ok=True)
        # 创建空 arxiv_meta.db (复用 schema)
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arxiv_meta (
                arxiv_id TEXT PRIMARY KEY, title TEXT, authors TEXT, abstract TEXT,
                categories TEXT, doi TEXT, journal_ref TEXT, update_date TEXT,
                source TEXT DEFAULT '', imported_at TEXT DEFAULT (datetime('now')))
        """)
        conn.close()

        report = run_audit(db_path=db_path)
        assert report["db_exists"]
        assert report["total"] == 0
        assert "sources" in report

    def test_audit_with_data(self, test_env):
        """有数据时的审计"""
        # 先建 arxiv_meta.db 并写数据
        db_path = os.path.join(os.getcwd(), "data", "arxiv_meta.db")
        os.makedirs(os.path.join(os.getcwd(), "data"), exist_ok=True)
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arxiv_meta (
                arxiv_id TEXT PRIMARY KEY, title TEXT, authors TEXT, abstract TEXT,
                categories TEXT, doi TEXT, journal_ref TEXT, update_date TEXT,
                source TEXT DEFAULT '', imported_at TEXT DEFAULT (datetime('now')))
        """)
        conn.execute("""
            INSERT INTO arxiv_meta (arxiv_id, title, source)
            VALUES (?, ?, ?)
        """, ("2501.10001", "Test Paper 1", "oai"))
        conn.execute("""
            INSERT INTO arxiv_meta (arxiv_id, title, source)
            VALUES (?, ?, ?)
        """, ("2501.10002", "Test Paper 2", "kaggle"))
        conn.commit()
        conn.close()

        from hfpclawer.audit import run_audit
        report = run_audit(db_path=db_path)
        assert report["total"] == 2
        assert report["sources"].get("oai", {}).get("count") == 1
        assert report["sources"].get("kaggle", {}).get("count") == 1

    def test_audit_source_column_migration(self):
        """验证 arxiv_meta 表 source 列迁移"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = sqlite3.connect(db_path)
            # 创建旧表（无 source 列，新 schema 有 source）
            old_schema = """CREATE TABLE IF NOT EXISTS arxiv_meta (
                arxiv_id TEXT PRIMARY KEY, title TEXT, authors TEXT, abstract TEXT,
                categories TEXT, doi TEXT, journal_ref TEXT, update_date TEXT,
                imported_at TEXT DEFAULT (datetime('now')));"""
            conn.executescript(old_schema)
            conn.close()

            # 用 MIGRATE_ADD_SOURCE 迁移
            from hfpclawer.download.oai import MIGRATE_ADD_SOURCE
            conn2 = sqlite3.connect(db_path)
            try:
                conn2.execute(MIGRATE_ADD_SOURCE)
            except sqlite3.OperationalError:
                pass  # 列已存在（测试中应该不会触发）
            conn2.close()

            # 验证 source 列已添加
            conn3 = sqlite3.connect(db_path)
            cols = [r[1] for r in conn3.execute("PRAGMA table_info(arxiv_meta)").fetchall()]
            assert "source" in cols, f"source 列缺失: {cols}"
            conn3.close()

    def test_audit_cli_help(self, test_env):
        result = runner.invoke(app, ["audit", "--help"])
        assert result.exit_code == 0
        assert "审计" in result.output

    def test_audit_json_output(self, test_env):
        # 先建 arxiv_meta.db
        db_path = os.path.join(os.getcwd(), "data", "arxiv_meta.db")
        os.makedirs(os.path.join(os.getcwd(), "data"), exist_ok=True)
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arxiv_meta (
                arxiv_id TEXT PRIMARY KEY, title TEXT, authors TEXT, abstract TEXT,
                categories TEXT, doi TEXT, journal_ref TEXT, update_date TEXT,
                source TEXT DEFAULT '', imported_at TEXT DEFAULT (datetime('now')))
        """)
        conn.close()

        result = runner.invoke(app, ["audit", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "db_path" in data
        assert "sources" in data
        assert "total" in data

    def test_audit_state_files(self, test_env):
        """验证状态文件检测"""
        # 建 data 目录和 arxiv_meta.db
        data_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(data_dir, exist_ok=True)
        db_path = os.path.join(data_dir, "arxiv_meta.db")
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arxiv_meta (
                arxiv_id TEXT PRIMARY KEY, title TEXT, authors TEXT, abstract TEXT,
                categories TEXT, doi TEXT, journal_ref TEXT, update_date TEXT,
                source TEXT DEFAULT '', imported_at TEXT DEFAULT (datetime('now')))
        """)
        conn.close()

        # 手动创建 state JSON
        state_path = os.path.join(data_dir, "test_source_download_state.json")
        with open(state_path, "w") as f:
            json.dump({
                "source": "test_source",
                "status": "done",
                "total_new": 42,
                "total_fetched": 100,
                "last_update": "2026-05-13T00:00:00",
                "checksum": "abc123",
                "error": "",
            }, f)

        try:
            from hfpclawer.audit import run_audit
            report = run_audit(db_path=db_path, data_dir=data_dir)
            state_files = report.get("state_files", [])
            assert len(state_files) >= 1
            matched = [s for s in state_files if s["source"] == "test_source"]
            assert len(matched) == 1
            assert matched[0]["status"] == "done"
            assert matched[0]["total_new"] == 42
        finally:
            if os.path.exists(state_path):
                os.unlink(state_path)
