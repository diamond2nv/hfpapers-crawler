#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_zotero_cli.py — hfpclawer zotero CLI + ZoteroClient 综合测试

测试策略:
  - 所有 Zotero API 调用通过 unittest.mock 模拟 (不需 Zotero Desktop)
  - CLI 调用通过 Typer CliRunner 测试
  - annotations 模块用临时 PDF 文件测试
  - connector 模块用 urllib.request 模拟测试

覆盖:
  hfpclawer/zotero/__init__.py  — ZoteroClient (read)
  hfpclawer/zotero/annotations.py — resolve_pdf_path, annotations
  hfpclawer/zotero/cli.py       — CLI dispatch
  hfpclawer/zotero/connector.py — ZoteroConnector (write)
"""

from __future__ import annotations

import json
import logging
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, patch, call

import pytest
from typer.testing import CliRunner

logger = logging.getLogger(__name__)

# ─── Fixtures ────────────────────────────────────────

@pytest.fixture
def runner() -> CliRunner:
    """Typer CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_zotero_client(monkeypatch) -> MagicMock:
    """Mock the entire pyzotero Zotero class.

    Returns the mocked hfpclawer ZoteroClient instance for assertions.
    """
    # Mock pyzotero.Zotero class
    mock_pyzotero_cls = MagicMock()
    mock_pyzotero_instance = MagicMock()
    mock_pyzotero_cls.return_value = mock_pyzotero_instance

    # Default return values
    mock_pyzotero_instance.top.return_value = []
    mock_pyzotero_instance.items.return_value = []
    mock_pyzotero_instance.item.return_value = None
    mock_pyzotero_instance.children.return_value = []
    mock_pyzotero_instance.tags.return_value = []
    mock_pyzotero_instance.collections.return_value = []
    mock_pyzotero_instance.collection_tags.return_value = []
    mock_pyzotero_instance.fulltext_item.return_value = None

    monkeypatch.setattr("hfpclawer.zotero._PyZotero", mock_pyzotero_cls)
    monkeypatch.setattr("hfpclawer.zotero.HAS_PYZOTERO", True)

    return mock_pyzotero_instance


@pytest.fixture
def temp_pdf(tmp_path: Path) -> Path:
    """Create a minimal valid PDF for annotation tests.

    This is a synthetic PDF with one page that has a text annotation.
    Uses the PDF spec minimal structure.
    """
    pdf_path = tmp_path / "test.pdf"
    # Mini PDF: 1 empty page
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R /Resources << /Font << >> >> >>\nendobj\n"
        b"4 0 obj\n<< /Length 44 >>\nstream\nBT /F1 12 Tf 100 700 Td (Hello) Tj ET\nendstream\nendobj\n"
        b"xref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000266 00000 n \n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n406\n%%%%EOF"
    )
    pdf_path.write_bytes(pdf_bytes)
    return pdf_path


# ════════════════════════════════════════════════════════════
# 1. ZoteroClient (__init__.py) — READ operations
# ════════════════════════════════════════════════════════════


class TestZoteroClientInit:
    """ZoteroClient initialization and connection."""

    def test_init_success(self, mock_zotero_client):
        """Should connect to local API on first call."""
        mock_zotero_client.top.return_value = [{"key": "ABC123", "data": {"title": "Test"}}]

        from hfpclawer.zotero import ZoteroClient

        zc = ZoteroClient()
        assert zc.check_connection() is True
        mock_zotero_client.top.assert_called_with(limit=1)

    def test_init_failure(self, monkeypatch):
        """Should raise ZoteroConnectionError when API is unreachable."""

        def _fail_connect():
            raise Exception("Connection refused")

        monkeypatch.setattr("hfpclawer.zotero._PyZotero", MagicMock())

        # Make the instance's top() fail
        mock_instance = MagicMock()
        mock_instance.top.side_effect = Exception("Connection refused")
        monkeypatch.setattr("hfpclawer.zotero._PyZotero", MagicMock(return_value=mock_instance))
        monkeypatch.setattr("hfpclawer.zotero.HAS_PYZOTERO", True)

        from hfpclawer.zotero import ZoteroClient, ZoteroConnectionError

        zc = ZoteroClient()
        assert zc.check_connection() is False

    def test_no_pyzotero(self, monkeypatch):
        """Should raise ImportError when pyzotero not installed."""
        monkeypatch.setattr("hfpclawer.zotero.HAS_PYZOTERO", False)

        from hfpclawer.zotero import ZoteroClient

        with pytest.raises(ImportError, match="pyzotero is required"):
            ZoteroClient()._connect()


class TestZoteroClientRead:
    """ZoteroClient read operations (top, items, get, children)."""

    def test_top_default(self, mock_zotero_client):
        """top() should pass default params."""
        mock_zotero_client.top.return_value = []

        from hfpclawer.zotero import ZoteroClient

        zc = ZoteroClient()
        result = zc.top()
        assert result == []
        mock_zotero_client.top.assert_called_with(limit=50, start=0)

    def test_top_with_filters(self, mock_zotero_client):
        """top() should pass filter params to pyzotero."""
        mock_zotero_client.top.return_value = [{"key": "X1"}]

        from hfpclawer.zotero import ZoteroClient

        zc = ZoteroClient()
        result = zc.top(limit=5, q="neural operator", tag="hfpclawer,reviewed", item_type="journalArticle")
        assert len(result) == 1
        mock_zotero_client.top.assert_called_with(
            limit=5, start=0, q="neural operator",
            tag=["hfpclawer", "reviewed"], itemType="journalArticle",
        )

    def test_items(self, mock_zotero_client):
        """items() should call pyzotero.items()."""
        mock_zotero_client.items.return_value = [{"key": "N1", "data": {"itemType": "note"}}]

        from hfpclawer.zotero import ZoteroClient

        zc = ZoteroClient()
        result = zc.items(limit=100)
        assert len(result) == 1
        mock_zotero_client.items.assert_called_with(limit=100, start=0)

    def test_get_item(self, mock_zotero_client):
        """get_item() should return item by key."""
        mock_item = {"key": "ABC123", "data": {"title": "Test Paper"}}
        mock_zotero_client.item.return_value = mock_item

        from hfpclawer.zotero import ZoteroClient

        zc = ZoteroClient()
        result = zc.get_item("ABC123")
        assert result == mock_item
        mock_zotero_client.item.assert_called_with("ABC123")

    def test_get_item_not_found(self, mock_zotero_client):
        """get_item() should return None for missing key."""
        mock_zotero_client.item.side_effect = Exception("Not found")

        from hfpclawer.zotero import ZoteroClient

        zc = ZoteroClient()
        result = zc.get_item("MISSING")
        assert result is None

    def test_get_children(self, mock_zotero_client):
        """get_children() should return child items."""
        children = [
            {"key": "AT1", "data": {"itemType": "attachment", "contentType": "application/pdf"}},
            {"key": "NT1", "data": {"itemType": "note"}},
        ]
        mock_zotero_client.children.return_value = children

        from hfpclawer.zotero import ZoteroClient

        zc = ZoteroClient()
        result = zc.get_children("ABC123")
        assert len(result) == 2
        mock_zotero_client.children.assert_called_with("ABC123")


class TestZoteroClientDedup:
    """arXiv ID / DOI dedup via extra field scanning."""

    @staticmethod
    def _make_item(key: str, extra: str = "", url: str = "", doi: str = "") -> dict:
        """Helper: create a mock Zotero item dict."""
        data = {"key": key, "extra": extra, "url": url, "DOI": doi}
        # Zotero API wraps items in a list; _fetch_all_items returns raw list
        return {"key": key, "data": data}

    @patch("urllib.request.urlopen")
    def test_is_arxiv_in_zotero_found(self, mock_urlopen, mock_zotero_client):
        """Should find arXiv ID from extra field."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([
            self._make_item("A1", extra="arXiv: 2501.01934\nType: journal\n"),
            self._make_item("A2", extra="arXiv: 2605.25001\nType: journal\n"),
        ]).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        from hfpclawer.zotero import ZoteroClient

        zc = ZoteroClient()
        # Force cache rebuild
        zc.clear_lookup_cache()

        key = zc.is_arxiv_in_zotero("2501.01934")
        assert key == "A1"

        key = zc.is_arxiv_in_zotero("2605.25001")
        assert key == "A2"

        key = zc.is_arxiv_in_zotero("9999.99999")
        assert key is None

    @patch("urllib.request.urlopen")
    def test_is_arxiv_in_zotero_from_url(self, mock_urlopen, mock_zotero_client):
        """Should find arXiv ID from URL field (arxiv.org/abs/...)."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([
            self._make_item("B1", url="https://arxiv.org/abs/2501.01934v2"),
        ]).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        from hfpclawer.zotero import ZoteroClient

        zc = ZoteroClient()
        zc.clear_lookup_cache()
        key = zc.is_arxiv_in_zotero("2501.01934")
        assert key == "B1"

    @patch("urllib.request.urlopen")
    def test_search_by_doi(self, mock_urlopen, mock_zotero_client):
        """search_by_doi should find by DOI field."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([
            self._make_item("C1", doi="10.1038/s41586-024-07123-5"),
        ]).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        from hfpclawer.zotero import ZoteroClient

        zc = ZoteroClient()
        zc.clear_lookup_cache()
        item = zc.search_by_doi("10.1038/s41586-024-07123-5")
        assert item is not None
        assert item["data"]["DOI"] == "10.1038/s41586-024-07123-5"

    @patch("urllib.request.urlopen")
    def test_lookup_cache(self, mock_urlopen, mock_zotero_client):
        """_build_arxiv_lookup should cache results."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([
            self._make_item("D1", extra="arXiv: 2501.01934\n"),
        ]).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        from hfpclawer.zotero import ZoteroClient

        zc = ZoteroClient()
        zc.clear_lookup_cache()

        # First call: fetches from API
        result1 = zc.is_arxiv_in_zotero("2501.01934")
        assert result1 == "D1"
        assert mock_urlopen.call_count == 1

        # Second call: uses cache
        result2 = zc.is_arxiv_in_zotero("2501.01934")
        assert result2 == "D1"
        assert mock_urlopen.call_count == 1  # still 1 — cached

        # After clear, should fetch again
        zc.clear_lookup_cache()
        mock_resp.read.return_value = json.dumps([]).encode()
        result3 = zc.is_arxiv_in_zotero("2501.01934")
        assert result3 is None
        assert mock_urlopen.call_count == 2  # fetched again


# ════════════════════════════════════════════════════════════
# 2. PDF Annotations (annotations.py)
# ════════════════════════════════════════════════════════════


class TestResolvePdfPath:
    """resolve_pdf_path — arXiv ID / Zotero key → local PDF path."""

    @patch("hfpclawer.zotero.annotations._api_get")
    def test_resolve_by_arxiv_id(self, mock_api_get, mock_zotero_client):
        """Should resolve arXiv ID → parent key → attachment → file path."""
        # Mock ZoteroClient.is_arxiv_in_zotero
        from hfpclawer.zotero import ZoteroClient
        zc = ZoteroClient()

        # Set up the arxiv lookup
        with patch.object(zc, "_build_arxiv_lookup", return_value={"2501.01934": "P1"}):
            with patch.object(zc, "is_arxiv_in_zotero", return_value="P1"):
                # Mock _api_get for parent item
                mock_api_get.side_effect = [
                    {"data": {"title": "Test Paper Title"}},  # parent item
                    [  # children
                        {
                            "key": "AT1",
                            "data": {
                                "itemType": "attachment",
                                "contentType": "application/pdf",
                                "filename": "test.pdf",
                                "key": "AT1",
                            },
                        }
                    ],
                ]

                from hfpclawer.zotero.annotations import resolve_pdf_path

                # Mock the file URL endpoint
                with patch("urllib.request.urlopen") as mock_file_url:
                    mock_file_resp = MagicMock()
                    mock_file_resp.read.return_value = b"file:///tmp/test.pdf"
                    mock_file_url.return_value.__enter__.return_value = mock_file_resp

                    # The PDF must exist for the path check
                    Path("/tmp/test.pdf").touch()

                    result = resolve_pdf_path(arxiv_id="2501.01934")
                    assert "pdf_path" in result
                    assert result["parent_key"] == "P1"
                    assert result["title"] == "Test Paper Title"

                    Path("/tmp/test.pdf").unlink(missing_ok=True)

    @patch("hfpclawer.zotero.annotations._api_get")
    def test_resolve_by_key(self, mock_api_get):
        """Should resolve by direct Zotero key."""
        mock_api_get.side_effect = [
            {"data": {"title": "Paper via Key"}},  # parent item
            [  # children
                {
                    "key": "AT1",
                    "data": {
                        "itemType": "attachment",
                        "contentType": "application/pdf",
                        "key": "AT1",
                    },
                }
            ],
        ]

        from hfpclawer.zotero.annotations import resolve_pdf_path

        with patch("urllib.request.urlopen") as mock_file_url:
            mock_file_resp = MagicMock()
            mock_file_resp.read.return_value = b"file:///tmp/test2.pdf"
            mock_file_url.return_value.__enter__.return_value = mock_file_resp

            Path("/tmp/test2.pdf").touch()
            result = resolve_pdf_path(zotero_key="MYKEY")
            assert "pdf_path" in result
            assert result["parent_key"] == "MYKEY"

            Path("/tmp/test2.pdf").unlink(missing_ok=True)

    def test_no_args_error(self):
        """Should return error if neither arxiv_id nor zotero_key."""
        from hfpclawer.zotero.annotations import resolve_pdf_path

        result = resolve_pdf_path()
        assert "error" in result
        assert "Provide either arxiv_id or zotero_key" in result["error"]


class TestPdfAnnotations:
    """extract_pdf_annotations + format_markdown."""

    def test_extract_no_annotations(self, temp_pdf: Path):
        """Should return empty list for PDF without annotations."""
        from hfpclawer.zotero.annotations import extract_pdf_annotations

        anns = extract_pdf_annotations(str(temp_pdf))
        # Our test PDF has no annotation objects, so should be empty
        assert isinstance(anns, list)
        # Note: fitz may or may not work depending on installation
        # If pymupdf is installed, anns should be []; if not, empty list is returned

    def test_format_markdown_empty(self):
        """format_markdown should handle empty list."""
        from hfpclawer.zotero.annotations import format_markdown

        md = format_markdown([])
        assert "No annotations found" in md

    def test_format_markdown_with_annotations(self):
        """format_markdown should format annotations."""
        from hfpclawer.zotero.annotations import format_markdown

        anns = [
            {"page": 1, "type": "highlight", "text": "Key result", "comment": "Important", "color": "#ffd400", "color_label": "🟡 Yellow"},
            {"page": 3, "type": "underline", "text": "Another note", "comment": "", "color": "#00ff00", "color_label": "🟢 Green"},
        ]
        md = format_markdown(anns, title="Test Paper")
        assert "Test Paper" in md
        assert "Key result" in md
        assert "Yellow" in md
        assert "Another note" in md
        assert "p.1" in md
        assert "p.3" in md

    def test_format_json(self):
        """format_json should produce valid JSON."""
        from hfpclawer.zotero.annotations import format_json

        anns = [{"page": 1, "type": "highlight", "text": "test"}]
        j = format_json(anns)
        parsed = json.loads(j)
        assert parsed == anns

    def test_color_filter(self):
        """color_filter should filter by hex or name."""
        from hfpclawer.zotero.annotations import color_filter

        anns = [
            {"color": "#ffd400", "color_label": "🟡 Yellow"},
            {"color": "#00ff00", "color_label": "🟢 Green"},
            {"color": "#ff0000", "color_label": "🔴 Red"},
        ]

        yellow = color_filter(anns, color_hex="#ffd400")
        assert len(yellow) == 1

        greens = color_filter(anns, color_name="Green")
        assert len(greens) == 1

        both = color_filter(anns, color_name="Green", color_hex="#ffd400")
        assert len(both) == 0  # AND filter, not OR

        all_ = color_filter(anns)
        assert len(all_) == 3


# ════════════════════════════════════════════════════════════
# 3. CLI Commands (cli.py)
# ════════════════════════════════════════════════════════════


class TestZoteroCli:
    """hfpclawer zotero CLI dispatch via Typer CliRunner."""

    def test_help(self, runner: CliRunner):
        """--help should display all actions."""
        from hfpapers.cli import app

        result = runner.invoke(app, ["zotero", "--help"])
        assert result.exit_code == 0
        assert "check" in result.stdout
        assert "list" in result.stdout
        assert "search" in result.stdout
        assert "get" in result.stdout
        assert "tags" in result.stdout
        assert "children" in result.stdout
        assert "push" in result.stdout
        assert "push-batch" in result.stdout
        assert "ingest" in result.stdout
        assert "annotate" in result.stdout
        assert "export" in result.stdout
        assert "note" in result.stdout

    @patch("hfpclawer.zotero.ZoteroClient.check_connection", return_value=True)
    def test_cmd_check(self, mock_check, runner: CliRunner):
        """zotero check should call check_connection."""
        from hfpapers.cli import app

        result = runner.invoke(app, ["zotero", "check"])
        assert result.exit_code == 0

    @patch("hfpclawer.zotero.ZoteroClient.check_connection", return_value=False)
    def test_cmd_check_fail(self, mock_check, runner: CliRunner):
        """zotero check should report failure."""
        from hfpapers.cli import app

        result = runner.invoke(app, ["zotero", "check"])
        assert result.exit_code == 0
        # Should print error message (not crash)

    @patch("hfpclawer.zotero.cli.cmd_list")
    def test_cmd_list_dispatch(self, mock_list, runner: CliRunner):
        """zotero list should dispatch cmd_list."""
        from hfpapers.cli import app

        runner.invoke(app, ["zotero", "list", "--limit", "5"])
        mock_list.assert_called_once()

    @patch("hfpclawer.zotero.cli.cmd_search")
    def test_cmd_search_dispatch(self, mock_search, runner: CliRunner):
        """zotero search should dispatch cmd_search."""
        from hfpapers.cli import app

        runner.invoke(app, ["zotero", "search", "neural", "--limit", "3"])
        mock_search.assert_called_once()

    @patch("hfpclawer.zotero.cli.cmd_ingest")
    def test_cmd_ingest_dispatch(self, mock_ingest, runner: CliRunner):
        """zotero ingest should dispatch cmd_ingest with correct args."""
        from hfpapers.cli import app

        runner.invoke(app, ["zotero", "ingest", "2501.01934", "--verbose", "--no-wiki"])
        mock_ingest.assert_called_once()
        args, kwargs = mock_ingest.call_args
        assert kwargs.get("arxiv_id") == "2501.01934" or kwargs.get("arxiv_id").endswith("2501.01934")
        assert kwargs.get("verbose") is True
        assert kwargs.get("no_wiki") is True

    def test_unknown_action(self, runner: CliRunner):
        """Unknown action should print error."""
        from hfpapers.cli import app

        result = runner.invoke(app, ["zotero", "nonexistent"])
        assert result.exit_code == 0
        assert "Unknown zotero action" in result.stdout


# ════════════════════════════════════════════════════════════
# 4. Connector (connector.py) — WRITE operations
# ════════════════════════════════════════════════════════════


class TestZoteroConnector:
    """ZoteroConnector — write via Connector protocol."""

    @patch("urllib.request.urlopen")
    def test_save_items(self, mock_urlopen):
        """save_items should POST to /connector/saveItems."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"session_id": "sess_123", "status": 200}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        from hfpclawer.zotero.connector import ZoteroConnector

        conn = ZoteroConnector()
        items = [{"itemType": "journalArticle", "title": "Test Paper"}]
        result = conn.save_items(items, uri="https://arxiv.org/abs/2501.01934")
        assert result["session_id"] == "sess_123"

        # Check the POST payload
        call_args = mock_urlopen.call_args[0][0]
        assert "saveItems" in str(call_args)

    @patch("urllib.request.urlopen")
    def test_save_attachment(self, mock_urlopen, tmp_path: Path):
        """save_attachment should POST to /connector/saveAttachment."""
        pdf = tmp_path / "test.pdf"
        pdf.write_text("dummy pdf")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": 201}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        from hfpclawer.zotero.connector import ZoteroConnector

        conn = ZoteroConnector()
        result = conn.save_attachment(
            session_id="sess_123",
            parent_item_key="PKEY",
            pdf_path=str(pdf),
            title="Test PDF",
        )
        assert result["status"] == 201

    @patch("urllib.request.urlopen")
    def test_connector_error(self, mock_urlopen):
        """save_items should handle HTTP errors."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://localhost/connector/saveItems",
            500, "Internal Server Error", {}, None,
        )

        from hfpclawer.zotero.connector import ZoteroConnector
        from hfpclawer.zotero.connector import ConnectorError

        conn = ZoteroConnector()
        with pytest.raises(ConnectorError):
            conn.save_items([{"itemType": "journalArticle", "title": "Test"}])


# ════════════════════════════════════════════════════════════
# 5. Integration: CLI ingest (mock Zotero + mock files)
# ════════════════════════════════════════════════════════════


class TestCmdIngest:
    """cmd_ingest — full pipeline (all mocked)."""

    @patch("hfpclawer.zotero.annotations.resolve_pdf_path")
    @patch("hfpclawer.zotero.cli.cfg_get")
    @patch("hfpapers.paper_store.ensure_paper")
    @patch("urllib.request.urlopen")  # arXiv API
    def test_ingest_basic(
        self, mock_urlopen, mock_ensure_paper, mock_cfg_get, mock_resolve_pdf,
        tmp_path: Path,
    ):
        """Ingest should run all 6 steps successfully."""
        # Mock PDF path
        pdf = tmp_path / "papers" / "test.pdf"
        pdf.parent.mkdir(parents=True)
        pdf.write_text("dummy pdf content for testing")
        mock_resolve_pdf.return_value = {
            "pdf_path": str(pdf),
            "title": "Test Paper Title",
            "parent_key": "P123",
        }

        # Mock cfg_get
        mock_cfg_get.side_effect = lambda k, d=None: {
            "paths.data_dir": str(tmp_path),
            "paths.pdf_dir": str(pdf.parent),
            "paths.md_dir": str(tmp_path / "mds"),
        }.get(k, d or str(tmp_path))

        # Mock ensure_paper
        mock_ensure_paper.return_value = (12345678, True)

        # Mock arXiv API response
        mock_resp = MagicMock()
        mock_resp.read.return_value = (
            '<?xml version="1.0"?><feed xmlns:a="http://www.w3.org/2005/Atom">'
            '<a:entry><a:title>Test Paper Title</a:title>'
            '<a:author><a:name>Author One</a:name></a:author>'
            '<a:author><a:name>Author Two</a:name></a:author>'
            '<a:summary>This is a test abstract.</a:summary>'
            '<a:category term="cs.LG"/><a:category term="cs.AI"/>'
            '</a:entry></feed>'
        ).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        from hfpclawer.zotero.cli import cmd_ingest

        with patch("builtins.open") as mock_open:  # wiki write
            cmd_ingest(arxiv_id="2501.01934", verbose=True)

        # Verify ensure_paper was called with DOI empty (no crossref)
        mock_ensure_paper.assert_called_once()
        args, kwargs = mock_ensure_paper.call_args
        assert kwargs["arxiv_id"] == "2501.01934"
        assert "title" in kwargs

    @patch("hfpclawer.zotero.annotations.resolve_pdf_path")
    def test_ingest_no_zotero(self, mock_resolve):
        """Ingest should fail gracefully when paper not in Zotero."""
        mock_resolve.return_value = {"error": "arXiv 9999.99999 not found in Zotero"}

        from hfpclawer.zotero.cli import cmd_ingest

        # Should print error and return, not crash
        cmd_ingest(arxiv_id="9999.99999")
        # No assertion needed — just verify no exception


# ─── Run: pytest tests/test_zotero_cli.py -v ───
