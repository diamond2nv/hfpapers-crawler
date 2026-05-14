#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test paper_store module — SQLite storage + Snowflake ID + identifiers"""

import time
from datetime import datetime

from hfpapers.paper_store import (
    PaperRecord,
    PaperStore,
    get_store,
    snowflake_id,
    snowflake_timestamp,
)


class TestSnowflakeID:
    def test_snowflake_id_is_int_and_unique(self):
        ids = [snowflake_id() for _ in range(10)]
        assert all(isinstance(i, int) for i in ids)
        assert len(set(ids)) == 10

    def test_snowflake_id_increasing(self):
        id1 = snowflake_id()
        time.sleep(0.001)  # wait 1ms
        id2 = snowflake_id()
        assert id2 > id1

    def test_snowflake_timestamp(self):
        before = datetime.now()
        sf_id = snowflake_id()
        after = datetime.now()
        extracted = snowflake_timestamp(sf_id)
        # Allow 0.5s tolerance (local clock vs _EPOCH may drift slightly)
        assert (extracted - before).total_seconds() > -0.5
        assert (after - extracted).total_seconds() > -0.5

    def test_snowflake_worker_id(self):
        id1 = snowflake_id(worker_id=0)
        id2 = snowflake_id(worker_id=1)
        assert id1 != id2


class TestPaperStore:
    def test_init_db_creates_tables(self, paper_store: PaperStore):
        import sqlite3

        conn = sqlite3.connect(paper_store.db_path)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        names = {r[0] for r in tables}
        assert "papers" in names
        assert "identifiers" in names
        assert "crossref_cache" in names
        conn.close()

    def test_upsert_and_get_paper(self, paper_store: PaperStore):
        rec = PaperRecord(
            title="Test Paper", abstract="test", year=2024, source="pytest", relevance=80
        )
        sf_id = paper_store.upsert_paper(rec)
        assert sf_id > 0

        got = paper_store.get_paper_by_id(sf_id)
        assert got is not None
        assert got.title == "Test Paper"
        assert got.relevance == 80
        assert not got.verified

    def test_get_paper_not_found(self, paper_store: PaperStore):
        got = paper_store.get_paper_by_id(99999)
        assert got is None

    def test_update_paper(self, paper_store: PaperStore):
        sf_id = paper_store.upsert_paper(PaperRecord(title="Title", relevance=50))
        paper_store.update_paper(sf_id, relevance=90, code_url="https://github.com/test")
        got = paper_store.get_paper_by_id(sf_id)
        assert got.relevance == 90
        assert got.code_url == "https://github.com/test"

    def test_add_and_get_identifiers(self, paper_store: PaperStore):
        sf_id = paper_store.upsert_paper(PaperRecord(title="With IDs"))
        paper_store.add_identifier(sf_id, "arxiv", "2301.11167", source="pytest", confidence=0.9)
        paper_store.add_identifier(sf_id, "doi", "10.1234/test", source="crossref")
        ids = paper_store.get_identifiers(sf_id)
        assert len(ids) == 2
        types = {i.id_type for i in ids}
        assert "arxiv" in types
        assert "doi" in types

    def test_add_duplicate_identifier_ignored(self, paper_store: PaperStore):
        sf_id = paper_store.upsert_paper(PaperRecord(title="Dup"))
        first = paper_store.add_identifier(sf_id, "arxiv", "2301.11167")
        assert first is True
        # Duplicate INSERT OR IGNORE silently skipped
        second = paper_store.add_identifier(sf_id, "arxiv", "2301.11167")
        assert second is True  # INSERT OR IGNORE doesn't raise
        ids = paper_store.get_identifiers(sf_id)
        assert len(ids) == 1  # Only stored once

    def test_search_papers_by_keyword(self, paper_store: PaperStore):
        sf1 = paper_store.upsert_paper(PaperRecord(title="Fourier Neural Operator", relevance=90))
        sf2 = paper_store.upsert_paper(PaperRecord(title="DeepONet for PDEs", relevance=70))
        sf3 = paper_store.upsert_paper(PaperRecord(title="Quantum ML", relevance=10))
        paper_store.add_identifier(sf1, "arxiv", "2010.08895")
        paper_store.add_identifier(sf2, "arxiv", "1910.03193")
        paper_store.add_identifier(sf3, "arxiv", "2301.00000")

        results = paper_store.search_papers("neural")
        titles = [r.title for r in results]
        assert "Fourier Neural Operator" in titles

        results_all = paper_store.search_papers()
        assert len(results_all) == 3
        # Sorted by relevance descending
        assert results_all[0].relevance >= results_all[1].relevance >= results_all[2].relevance

    def test_find_paper_by_any_id(self, paper_store: PaperStore):
        sf_id = paper_store.upsert_paper(PaperRecord(title="Findable"))
        paper_store.add_identifier(sf_id, "arxiv", "9999.99999")
        paper_store.add_identifier(sf_id, "doi", "10.9999/test")

        by_arxiv = paper_store.find_paper_by_any_id("9999.99999")
        assert by_arxiv is not None
        assert by_arxiv.title == "Findable"

        by_doi = paper_store.find_paper_by_any_id("10.9999/test")
        assert by_doi is not None

    def test_verify_paper(self, paper_store: PaperStore):
        sf_id = paper_store.upsert_paper(PaperRecord(title="Verify Me"))
        paper_store.add_identifier(sf_id, "arxiv", "2301.11167")
        # Single type should not verify
        paper_store.verify_paper(sf_id)
        p = paper_store.get_paper_by_id(sf_id)
        assert not p.verified

        # Add second identifier type
        paper_store.add_identifier(sf_id, "doi", "10.1234/verify")
        paper_store.verify_paper(sf_id)
        p = paper_store.get_paper_by_id(sf_id)
        assert p.verified

    def test_stats(self, paper_store: PaperStore):
        sf1 = paper_store.upsert_paper(PaperRecord(title="A", relevance=80))
        sf2 = paper_store.upsert_paper(PaperRecord(title="B", relevance=50))
        paper_store.add_identifier(sf1, "arxiv", "2301.00001")
        paper_store.add_identifier(sf2, "arxiv", "2301.00002")
        paper_store.add_identifier(sf1, "doi", "10.1234/a")
        paper_store.verify_paper(sf1)

        s = paper_store.stats()
        assert s["papers_total"] == 2
        assert s["papers_verified"] == 1
        assert s["identifiers_total"] == 3


class TestGetStoreSingleton:
    def test_get_store_returns_same_instance(self):
        s1 = get_store()
        s2 = get_store()
        assert s1 is s2
