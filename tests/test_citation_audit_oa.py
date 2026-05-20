#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for citation_audit_oa.py — OpenAlex API client (mock network).

Architecture reference: academic-research-skills (CC BY-NC 4.0).
"""

from unittest.mock import patch

import pytest

from hfpclawer.citation_audit_oa import OAClient

# ─── Fixtures ─────────────────────────────────────


@pytest.fixture
def client():
    return OAClient()


_MOCK_PAPER = {
    "id": "https://openalex.org/W1234567890",
    "title": "Fourier Neural Operator for Parametric Partial Differential Equations",
    "publication_year": 2020,
    "doi": "https://doi.org/10.48550/arxiv.2010.08895",
    "primary_location": {
        "source": {"display_name": "ICLR 2021"},
    },
    "authorships": [
        {"author": {"display_name": "Zongyi Li"}},
        {"author": {"display_name": "Nikola Kovachki"}},
    ],
}


class TestOALookup:
    def test_verified(self, client):
        """Successful title search returns VERIFIED."""
        with patch.object(client, "_get", return_value={"results": [_MOCK_PAPER]}):
            result = client.lookup(
                "Fourier Neural Operator for Parametric Partial Differential Equations"
            )
        assert result["status"] == "VERIFIED"
        assert result["oa_id"] == "https://openalex.org/W1234567890"
        assert "Zongyi Li" in result["authors"]

    def test_not_found(self, client):
        """No results returns NOT_FOUND."""
        with patch.object(client, "_get", return_value={"results": []}):
            result = client.lookup("Nonexistent paper about unicorns")
        assert result["status"] == "NOT_FOUND"

    def test_low_similarity_not_found(self, client):
        """Candidate below threshold returns NOT_FOUND."""
        mock_data = {
            "results": [
                {
                    "id": "https://openalex.org/Wx",
                    "title": "Totally Unrelated Topic in Biology",
                    "publication_year": 2022,
                }
            ]
        }
        with patch.object(client, "_get", return_value=mock_data):
            result = client.lookup("Fourier Neural Operator")
        assert result["status"] == "NOT_FOUND"

    def test_error_network(self, client):
        """Network error returns ERROR gracefully."""
        with patch.object(client, "_get", side_effect=ConnectionError("timeout")):
            result = client.lookup("Any paper")
        assert result["status"] == "ERROR"
        assert "error" in result

    def test_throttle_429_then_success(self, client):
        """429 retry succeeds on second attempt — mock at urlopen level."""
        import json
        import urllib.error
        from unittest.mock import MagicMock

        call_count = [0]

        mock_paper = {
            "id": "https://openalex.org/W1234567890",
            "title": "Fourier Neural Operator",
            "publication_year": 2020,
            "primary_location": {"source": {"display_name": "ICLR 2021"}},
            "authorships": [{"author": {"display_name": "Zongyi Li"}}],
        }

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise urllib.error.HTTPError("/works", 429, "Too Many Requests", {}, None)
            mock_resp = MagicMock()
            mock_resp.__enter__.return_value.read.return_value = json.dumps({"results": [mock_paper]}).encode("utf-8")
            return mock_resp

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = side_effect
            result = client.lookup("Fourier Neural Operator")
        assert result["status"] == "VERIFIED"

    def test_venue_parsing(self, client):
        """Venue name should be extracted from primary_location."""
        mock_data = {
            "results": [{
                "id": "https://openalex.org/Wx",
                "title": "Fourier Neural Operator",
                "publication_year": 2020,
                "primary_location": {
                    "source": {"display_name": "NeurIPS 2023"},
                },
                "authorships": [],
            }]
        }
        with patch.object(client, "_get", return_value=mock_data):
            result = client.lookup("Fourier Neural Operator")
        assert result["venue"] == "NeurIPS 2023"


class TestOAGet:
    def test_404_returns_empty(self, client):
        """404 returns empty dict."""
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            "/works", 404, "Not Found", {}, None
        )):
            result = client._get("/works", {"search": "test"})
        assert result == {}
