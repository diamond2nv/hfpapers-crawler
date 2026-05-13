#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for audit module -- comprehensive coverage"""

import json
import os
import sqlite3
import tempfile

from typer.testing import CliRunner

runner = CliRunner()


def _create_arxiv_meta_db(db_path: str, papers: list[dict] = None):
    """Create arxiv_meta.db and insert test data"""
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


def _create_paper_store_db(db_path: str, papers: list[dict] = None):
    """Create papers.db and insert test data (with identifiers table)"""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS papers (
            sf_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            abstract TEXT DEFAULT '',
            year INTEGER DEFAULT 0,
            source TEXT DEFAULT '',
            venue TEXT DEFAULT '',
            relevance INTEGER DEFAULT 0,
            has_code INTEGER DEFAULT 0,
            code_url TEXT DEFAULT '',
            verified INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS identifiers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sf_id INTEGER NOT NULL,
            id_type TEXT NOT NULL,
            id_value TEXT NOT NULL,
            source TEXT DEFAULT '',
            confidence REAL DEFAULT 1.0,
            verified_at TEXT DEFAULT (datetime('now')),
            UNIQUE(id_type, id_value),
            FOREIGN KEY (sf_id) REFERENCES papers(sf_id)
        );
    """)
    for p in (papers or []):
        conn.execute(
            "INSERT INTO papers (sf_id, title, source, verified, year) VALUES (?, ?, ?, ?, ?)",
            (p["sf_id"], p["title"], p.get("source", ""), int(p.get("verified", False)), p.get("year", 2025)),
        )
        for id_rec in p.get("identifiers", []):
            conn.execute(
                "INSERT INTO identifiers (sf_id, id_type, id_value) VALUES (?, ?, ?)",
                (p["sf_id"], id_rec["type"], id_rec["value"]),
            )
    conn.commit()
    conn.close()


class TestArxivMetaAudit:
    """arxiv_meta layer audit test"""

    def test_empty_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "arxiv_meta.db")
            _create_arxiv_meta_db(db_path)
            from hfpclawer.audit import run_audit
            report = run_audit(db_path=db_path)
            assert report["db_exists"]
            assert report["total"] == 0
            assert report["sources"] == {}
            assert report["has_source_column"] is True

    def test_single_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "arxiv_meta.db")
            _create_arxiv_meta_db(db_path, [
                {"arxiv_id": "2501.0001", "title": "A", "source": "oai"},
                {"arxiv_id": "2501.0002", "title": "B", "source": "oai"},
            ])
            from hfpclawer.audit import run_audit
            report = run_audit(db_path=db_path)
            assert report["total"] == 2
            assert report["sources"]["oai"]["count"] == 2

    def test_multi_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "arxiv_meta.db")
            _create_arxiv_meta_db(db_path, [
                {"arxiv_id": "2501.0001", "title": "A", "source": "oai"},
                {"arxiv_id": "2501.0002", "title": "B", "source": "kaggle"},
                {"arxiv_id": "2501.0003", "title": "C", "source": "kaggle"},
            ])
            from hfpclawer.audit import run_audit
            report = run_audit(db_path=db_path)
            assert report["total"] == 3
            assert report["sources"]["oai"]["count"] == 1
            assert report["sources"]["kaggle"]["count"] == 2

    def test_unknown_source(self):
        """Empty string source should show as unknown"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "arxiv_meta.db")
            _create_arxiv_meta_db(db_path, [
                {"arxiv_id": "2501.0001", "title": "A", "source": ""},
            ])
            from hfpclawer.audit import run_audit
            report = run_audit(db_path=db_path)
            assert "unknown" in report["sources"]
            assert report["sources"]["unknown"]["count"] == 1

    def test_db_not_exists(self):
        from hfpclawer.audit import run_audit
        report = run_audit(db_path="/nonexistent/db.db")
        assert not report["db_exists"]
        assert report["total"] == 0
        assert report["sources"] == {}

    def test_no_source_column_legacy(self):
        """Audit fallback for old table (no source column)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "arxiv_meta.db")
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE arxiv_meta (
                    arxiv_id TEXT PRIMARY KEY, title TEXT)
            """)
            conn.execute("INSERT INTO arxiv_meta (arxiv_id, title) VALUES ('2501.0001', 'A')")
            conn.commit()
            conn.close()
            from hfpclawer.audit import run_audit
            report = run_audit(db_path=db_path)
            assert report["has_source_column"] is False
            assert "legacy" in report["sources"]
            assert report["sources"]["legacy"]["count"] == 1

    def test_imported_at_timestamps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "arxiv_meta.db")
            _create_arxiv_meta_db(db_path, [
                {"arxiv_id": "2501.0001", "title": "A", "source": "oai"},
            ])
            from hfpclawer.audit import run_audit
            report = run_audit(db_path=db_path)
            oai = report["sources"]["oai"]
            assert oai["first_import"] is not None
            assert oai["last_import"] is not None

    def test_source_column_migration(self):
        """Verify old table ALTER TABLE migration success"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = sqlite3.connect(db_path)
            old_schema = """CREATE TABLE arxiv_meta (
                arxiv_id TEXT PRIMARY KEY, title TEXT, authors TEXT, abstract TEXT,
                categories TEXT, doi TEXT, journal_ref TEXT, update_date TEXT,
                imported_at TEXT DEFAULT (datetime('now')));"""
            conn.executescript(old_schema)
            conn.close()

            from hfpclawer.download.oai import MIGRATE_ADD_SOURCE
            conn2 = sqlite3.connect(db_path)
            try:
                conn2.execute(MIGRATE_ADD_SOURCE)
            except sqlite3.OperationalError:
                pass
            conn2.close()

            conn3 = sqlite3.connect(db_path)
            cols = [r[1] for r in conn3.execute("PRAGMA table_info(arxiv_meta)").fetchall()]
            assert "source" in cols
            conn3.close()


class TestStateFilesAudit:
    """State file audit test"""

    def test_no_state_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from hfpclawer.audit import _get_state_paths
            state_files = _get_state_paths(tmpdir)
            assert state_files == []

    def test_single_state_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "oai_download_state.json")
            with open(state_path, "w") as f:
                json.dump({"source": "oai", "status": "done", "total_new": 100}, f)
            from hfpclawer.audit import _get_state_paths
            state_files = _get_state_paths(tmpdir)
            assert len(state_files) == 1
            assert state_files[0]["source"] == "oai"
            assert state_files[0]["status"] == "done"
            assert state_files[0]["total_new"] == 100

    def test_multiple_state_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for src in ["oai", "kaggle", "test"]:
                with open(os.path.join(tmpdir, f"{src}_download_state.json"), "w") as f:
                    json.dump({"source": src, "status": "done"}, f)
            from hfpclawer.audit import _get_state_paths
            state_files = _get_state_paths(tmpdir)
            assert len(state_files) == 3
            sources = {sf["source"] for sf in state_files}
            assert sources == {"oai", "kaggle", "test"}

    def test_corrupted_state_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "bad_download_state.json")
            with open(state_path, "w") as f:
                f.write("{invalid json")
            from hfpclawer.audit import _get_state_paths
            state_files = _get_state_paths(tmpdir)
            assert len(state_files) == 1
            assert "parse_error" in state_files[0]["status"]

    def test_state_file_with_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "oai_download_state.json")
            with open(state_path, "w") as f:
                json.dump({"source": "oai", "status": "failed", "error": "Network timeout"}, f)
            from hfpclawer.audit import _get_state_paths
            state_files = _get_state_paths(tmpdir)
            assert state_files[0]["status"] == "failed"
            assert "Network timeout" in state_files[0]["error"]


class TestJsonlAudit:
    """JSONL file audit test"""

    def test_jsonl_not_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from hfpclawer.audit import _get_jsonl_info
            info = _get_jsonl_info(tmpdir)
            assert info["exists"] is False

    def test_jsonl_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = os.path.join(tmpdir, "arxiv_metadata.jsonl")
            with open(jsonl_path, "w") as f:
                for i in range(100):
                    f.write(f'{{"id": "2501.{i:04d}", "title": "Paper {i}"}}\n')
            from hfpclawer.audit import _get_jsonl_info
            info = _get_jsonl_info(tmpdir)
            assert info["exists"] is True
            assert info["lines"] == 100
            assert info["size_mb"] >= 0


class TestPaperStoreAudit:
    """paper_store (papers.db) layer cross-validation audit test"""

    def test_paper_store_empty(self):
        from hfpapers.paper_store import PaperStore
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PaperStore(db_path=os.path.join(tmpdir, "papers.db"))
            from hfpclawer.audit import run_paper_store_audit
            report = run_paper_store_audit(store)
            assert report["total_papers"] == 0
            assert report["verified_papers"] == 0
            assert report["with_code"] == 0
            assert report["dual_id_papers"] == 0
            assert report["identifier_types"] == []

    def test_paper_store_no_ids(self):
        """Only papers, no identifiers"""
        from hfpapers.paper_store import PaperRecord, PaperStore
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PaperStore(db_path=os.path.join(tmpdir, "papers.db"))
            store.upsert_paper(PaperRecord(title="Paper A", source="test"))
            store.upsert_paper(PaperRecord(title="Paper B", source="test"))
            from hfpclawer.audit import run_paper_store_audit
            report = run_paper_store_audit(store)
            assert report["total_papers"] == 2
            assert report["dual_id_papers"] == 0

    def test_dual_id_identifiers(self, paper_store):
        """Verify dual ID audit via paper_store fixture"""
        from hfpapers.paper_store import PaperRecord
        from hfpclawer.audit import run_paper_store_audit

        # Paper A: arXiv + DOI dual identifiers
        sf_a = paper_store.upsert_paper(PaperRecord(title="Paper A", source="test", verified=True))
        paper_store.add_identifier(sf_a, "arxiv", "2501.10001", source="test")
        paper_store.add_identifier(sf_a, "doi", "10.1234/test.2025.10001", source="crossref")

        # Paper B: Only arXiv
        sf_b = paper_store.upsert_paper(PaperRecord(title="Paper B", source="test"))
        paper_store.add_identifier(sf_b, "arxiv", "2501.10002", source="test")

        # Paper C: arXiv + DOI + OpenReview three identifiers
        sf_c = paper_store.upsert_paper(PaperRecord(title="Paper C", source="test", verified=True))
        paper_store.add_identifier(sf_c, "arxiv", "2501.10003", source="test")
        paper_store.add_identifier(sf_c, "doi", "10.1234/test.2025.10003", source="crossref")
        paper_store.add_identifier(sf_c, "openreview", "abc123", source="pns")

        report = run_paper_store_audit(paper_store)
        assert report["total_papers"] == 3
        assert report["verified_papers"] == 2
        assert report["dual_id_papers"] == 2  # A and C
        assert report["with_code"] == 0
        assert set(report["identifier_types"]) == {"arxiv", "doi", "openreview"}
        # Count per type
        type_counts = {t["type"]: t["count"] for t in report["identifier_type_stats"]}
        assert type_counts["arxiv"] == 3
        assert type_counts["doi"] == 2
        assert type_counts["openreview"] == 1

    def test_dual_id_no_arxiv(self):
        """Only DOI without arXiv does not count as dual"""
        from hfpapers.paper_store import PaperRecord, PaperStore
        from hfpclawer.audit import run_paper_store_audit
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PaperStore(db_path=os.path.join(tmpdir, "papers.db"))
            sf = store.upsert_paper(PaperRecord(title="DOI Only", source="test"))
            store.add_identifier(sf, "doi", "10.1234/only-doi", source="crossref")
            report = run_paper_store_audit(store)
            assert report["dual_id_papers"] == 0  # Does not count, because no arxiv

    def test_with_code_flag(self):
        from hfpapers.paper_store import PaperRecord, PaperStore
        from hfpclawer.audit import run_paper_store_audit
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PaperStore(db_path=os.path.join(tmpdir, "papers.db"))
            sf = store.upsert_paper(PaperRecord(title="Has Code", source="test",
                                                  has_code=True, code_url="https://github.com/x/y"))
            store.add_identifier(sf, "arxiv", "2501.10001")
            report = run_paper_store_audit(store)
            assert report["with_code"] == 1
            assert report["total_papers"] == 1

    def test_verify_ratio(self):
        """Verify ratio calculation"""
        from hfpapers.paper_store import PaperRecord, PaperStore
        from hfpclawer.audit import run_paper_store_audit
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PaperStore(db_path=os.path.join(tmpdir, "papers.db"))
            for i in range(10):
                sf = store.upsert_paper(PaperRecord(title=f"P{i}", source="test",
                                                      verified=(i < 7)))
            report = run_paper_store_audit(store)
            assert report["verified_papers"] == 7
            # dual_id_papers is 0 because no identifiers

    def test_identifier_type_breakdown(self):
        from hfpapers.paper_store import PaperRecord, PaperStore
        from hfpclawer.audit import run_paper_store_audit
        with tempfile.TemporaryDirectory() as tmpdir:
            store = PaperStore(db_path=os.path.join(tmpdir, "papers.db"))
            sf1 = store.upsert_paper(PaperRecord(title="P1"))
            store.add_identifier(sf1, "arxiv", "2501.0001")
            store.add_identifier(sf1, "doi", "10.1/abc")
            sf2 = store.upsert_paper(PaperRecord(title="P2"))
            store.add_identifier(sf2, "arxiv", "2501.0002")
            store.add_identifier(sf2, "issn", "1234-5678")
            report = run_paper_store_audit(store)
            type_stats = {t["type"]: t for t in report["identifier_type_stats"]}
            assert type_stats["arxiv"]["count"] == 2
            assert type_stats["doi"]["count"] == 1
            assert type_stats["issn"]["count"] == 1


class TestCombinedAudit:
    """Comprehensive audit test (arxiv_meta + paper_store)"""

    def test_full_audit_with_meta_and_store(self, paper_store, test_env):
        """Verify both databases are audited simultaneously via run_full_audit"""
        from hfpapers.paper_store import PaperRecord
        from hfpclawer.audit import run_audit, run_paper_store_audit

        # paper_store insert data
        sf = paper_store.upsert_paper(PaperRecord(title="Combined Paper", source="test"))
        paper_store.add_identifier(sf, "arxiv", "2501.00001")
        paper_store.add_identifier(sf, "doi", "10.1234/combined")

        # arxiv_meta insert data
        meta_db_path = os.path.join(os.getcwd(), "data", "arxiv_meta.db")
        os.makedirs(os.path.dirname(meta_db_path), exist_ok=True)
        _create_arxiv_meta_db(meta_db_path, [
            {"arxiv_id": "2501.00001", "title": "Combined Paper", "source": "oai", "doi": "10.1234/combined"},
        ])

        meta_report = run_audit(db_path=meta_db_path)
        store_report = run_paper_store_audit(store=paper_store)
        assert meta_report["total"] == 1
        assert store_report["total_papers"] == 1
        assert store_report["dual_id_papers"] == 1

    def test_full_audit_json_output(self):
        """Full audit JSON output format verification"""
        from hfpapers.paper_store import PaperStore
        from hfpclawer.audit import run_full_audit
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            store = PaperStore(db_path=os.path.join(tmpdir, "papers.db"))
            report = run_full_audit(db_path=db_path)
            # Check top-level structure
            for key in ["timestamp", "arxiv_meta", "paper_store"]:
                assert key in report, f"Missing key: {key}"
