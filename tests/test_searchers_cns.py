#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for CNS OA searchers — Europe PMC + Semantic Scholar"""

from unittest.mock import MagicMock, patch

import pytest

from hfpapers.searcher_registry import SearchResult

# ============================================================
# Europe PMCSearcher
# ============================================================


class TestEuropePMCSearcher:
    """Test EuropePMC searcher — mock API responses"""

    @pytest.fixture
    def mock_epmc_response(self):
        return {
            "version": "6.8",
            "hitCount": 2,
            "resultList": {
                "result": [
                    {
                        "id": "PMC12345",
                        "source": "MED",
                        "title": "Fourier Neural Operator for Burgers Equation",
                        "authorString": "Li Z, Kovachki N.",
                        "journalTitle": "Nature Communications",
                        "pubYear": "2025",
                        "doi": "10.1038/s41467-025-12345",
                        "abstractText": "We present an FNO framework.",
                        "hasPDF": "Y",
                        "citedByCount": 42,
                    },
                    {
                        "id": "PMC67890",
                        "source": "MED",
                        "title": "Physics-Informed DeepONet for PDE Discovery",
                        "authorString": "Lu L, Karniadakis GE.",
                        "journalTitle": "Nature Communications",
                        "pubYear": "2025",
                        "doi": "10.1038/s41467-025-67890",
                        "abstractText": "PI-DeepONet for governing PDEs.",
                        "hasPDF": "N",
                        "citedByCount": 15,
                    },
                ]
            },
        }

    @pytest.fixture
    def mock_s2_arxiv_response(self):
        return [
            {
                "paperId": "abc123",
                "externalIds": {
                    "DOI": "10.1038/s41467-025-12345",
                    "ArXiv": "2501.12345",
                },
            },
            {
                "paperId": "def456",
                "externalIds": {
                    "DOI": "10.1038/s41467-025-67890",
                    "ArXiv": "2502.67890",
                },
            },
        ]

    def test_search_returns_results(self, mock_epmc_response, mock_s2_arxiv_response):
        from hfpapers.searchers.europepmc import EuropePMCSearcher

        searcher = EuropePMCSearcher(journal="Nature Communications")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_epmc_response

        mock_s2 = MagicMock()
        mock_s2.status_code = 200
        mock_s2.json.return_value = mock_s2_arxiv_response

        with patch("requests.get", return_value=mock_resp), patch(
            "requests.post", return_value=mock_s2
        ):
            results = searcher.search_sync("neural operator Burgers", limit=25)

        assert len(results) == 2
        assert results[0].doi == "10.1038/s41467-025-12345"
        assert results[0].source == "europepmc"
        assert results[0].arxiv_id == "2501.12345"
        assert results[1].arxiv_id == "2502.67890"

    def test_search_empty_results(self):
        from hfpapers.searchers.europepmc import EuropePMCSearcher

        searcher = EuropePMCSearcher()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"resultList": {"result": []}}

        with patch("requests.get", return_value=mock_resp):
            results = searcher.search_sync("nonexistent")
        assert results == []

    def test_search_http_error(self):
        from hfpapers.searchers.europepmc import EuropePMCSearcher

        searcher = EuropePMCSearcher()
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch("requests.get", return_value=mock_resp):
            results = searcher.search_sync("test")
        assert results == []

    def test_search_network_error(self):
        from hfpapers.searchers.europepmc import EuropePMCSearcher

        searcher = EuropePMCSearcher()
        with patch("requests.get", side_effect=Exception("Connection refused")):
            results = searcher.search_sync("test")
        assert results == []

    def test_is_available(self):
        from hfpapers.searchers.europepmc import EuropePMCSearcher

        assert EuropePMCSearcher().is_available() is True

    def test_name_and_priority(self):
        from hfpapers.searchers.europepmc import EuropePMCSearcher

        s = EuropePMCSearcher()
        assert s.name == "europepmc"
        assert s.priority == 35


# ============================================================
# SemanticScholarSearcher
# ============================================================


class TestSemanticScholarSearcher:

    @pytest.fixture
    def mock_s2_response(self):
        return {
            "data": [
                {
                    "paperId": "s2paper123",
                    "title": "Neural Operators for Parametric PDEs",
                    "abstract": "A general framework for learning parametric PDEs.",
                    "year": 2025,
                    "externalIds": {
                        "DOI": "10.1126/sciadv.abc123",
                        "ArXiv": "2503.11111",
                    },
                    "openAccessPdf": {"url": "https://arxiv.org/pdf/2503.11111.pdf"},
                    "journal": {"name": "Science Advances"},
                    "authors": [{"name": "Jane Smith"}, {"name": "John Doe"}],
                    "citationCount": 88,
                },
                {
                    "paperId": "s2paper456",
                    "title": "PINO: Physics-Informed Neural Operators",
                    "abstract": "PINO combines operator learning with physics constraints.",
                    "year": 2025,
                    "externalIds": {"DOI": "10.1126/sciadv.def456"},
                    "openAccessPdf": None,
                    "journal": {"name": "Science Advances"},
                    "authors": [{"name": "Alice Wang"}],
                    "citationCount": 45,
                },
            ]
        }

    def test_search_returns_results(self, mock_s2_response):
        from hfpapers.searchers.semanticscholar import SemanticScholarSearcher

        searcher = SemanticScholarSearcher(journal="Science Advances")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_s2_response

        with patch("requests.get", return_value=mock_resp):
            results = searcher.search_sync("neural operator PDE")

        assert len(results) == 2
        assert results[0].arxiv_id == "2503.11111"
        assert results[0].doi == "10.1126/sciadv.abc123"
        assert results[0].source == "semanticscholar"
        assert results[1].arxiv_id == ""

    def test_search_empty(self):
        from hfpapers.searchers.semanticscholar import SemanticScholarSearcher

        searcher = SemanticScholarSearcher()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}

        with patch("requests.get", return_value=mock_resp):
            assert searcher.search_sync("nonexistent") == []

    def test_search_http_error(self):
        from hfpapers.searchers.semanticscholar import SemanticScholarSearcher

        searcher = SemanticScholarSearcher()
        mock_resp = MagicMock()
        mock_resp.status_code = 429

        with patch("requests.get", return_value=mock_resp):
            assert searcher.search_sync("test") == []

    def test_is_available(self):
        from hfpapers.searchers.semanticscholar import SemanticScholarSearcher

        assert SemanticScholarSearcher().is_available() is True

    def test_name_and_priority(self):
        from hfpapers.searchers.semanticscholar import SemanticScholarSearcher

        s = SemanticScholarSearcher()
        assert s.name == "semanticscholar"
        assert s.priority == 40

    def test_api_key_header(self):
        from hfpapers.searchers.semanticscholar import SemanticScholarSearcher

        searcher = SemanticScholarSearcher(api_key="test-key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}

        with patch("requests.get") as mock_get:
            mock_get.return_value = mock_resp
            searcher.search_sync("test")
            headers = mock_get.call_args[1].get("headers", {})
            assert headers.get("x-api-key") == "test-key"


# ============================================================
# DOI dedup path
# ============================================================


class TestDOIDedup:

    def test_doi_only_paper_accepted(self):
        from hfpapers.search_queue import SearchDispatcher

        d = SearchDispatcher(max_workers=1)
        results = [
            SearchResult(
                title="CNS Paper",
                abstract="Abs",
                source="europepmc",
                doi="10.1038/s41467-025-12345",
            )
        ]
        verified = d._dedup_and_verify(results)
        assert len(verified) == 1

    def test_doi_duplicate_blocked(self):
        from hfpapers.search_queue import SearchDispatcher

        d = SearchDispatcher(max_workers=1)
        results = [
            SearchResult(title="A", abstract="a", source="europepmc", doi="10.1234/x"),
            SearchResult(title="A2", abstract="a", source="semanticscholar", doi="10.1234/x"),
        ]
        verified = d._dedup_and_verify(results)
        assert len(verified) == 1

    def test_arxiv_and_doi_mixed(self):
        from hfpapers.search_queue import SearchDispatcher

        d = SearchDispatcher(max_workers=1)
        d._verify_enabled = False  # Don't hit real arXiv API for title check
        results = [
            SearchResult(arxiv_id="2501.12345", title="ArXiv", abstract="a", source="arxiv_local"),
            SearchResult(title="CNS", abstract="b", source="europepmc", doi="10.1038/x"),
        ]
        verified = d._dedup_and_verify(results)
        assert len(verified) == 2

    def test_no_id_skipped(self):
        from hfpapers.search_queue import SearchDispatcher

        d = SearchDispatcher(max_workers=1)
        results = [SearchResult(title="No ID", abstract="x", source="unknown")]
        verified = d._dedup_and_verify(results)
        assert len(verified) == 0
