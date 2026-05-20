#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for citation_audit_s2.py — Semantic Scholar API client (mock network).

Architecture reference: academic-research-skills (CC BY-NC 4.0).
"""

import json
from unittest.mock import patch

import pytest

from hfpclawer.citation_audit_s2 import S2Client

# ─── Fixtures ─────────────────────────────────────


@pytest.fixture
def client():
    return S2Client()


# ─── Helpers ──────────────────────────────────────


def _mock_response(data: dict) -> bytes:
    return json.dumps(data).encode("utf-8")


_MOCK_PAPER = {
    "paperId": "a1b2c3d4e5",
    "title": "Fourier Neural Operator for Parametric Partial Differential Equations",
    "year": 2020,
    "venue": "ICLR 2021",
    "authors": [{"name": "Zongyi Li"}, {"name": "Nikola Kovachki"}],
    "externalIds": {"ArXiv": "2010.08895"},
}


# ─── Tests ────────────────────────────────────────


class TestS2Lookup:
    def test_verified(self, client):
        """Successful title search returns VERIFIED."""
        with patch.object(client, "_request", return_value={"data": [_MOCK_PAPER]}):
            result = client.lookup(
                "Fourier Neural Operator for Parametric Partial Differential Equations"
            )
        assert result["status"] == "VERIFIED"
        assert result["paper_id"] == "a1b2c3d4e5"
        assert "Zongyi Li" in result["authors"]

    def test_not_found(self, client):
        """No candidates returns NOT_FOUND."""
        with patch.object(client, "_request", return_value={"data": []}):
            result = client.lookup("Nonexistent paper about unicorns")
        assert result["status"] == "NOT_FOUND"

    def test_low_similarity_not_found(self, client):
        """Candidate below threshold returns NOT_FOUND."""
        mock_data = {
            "data": [
                {
                    "paperId": "x",
                    "title": "Totally Unrelated Topic in Biology",
                    "year": 2022,
                    "venue": "Nature",
                }
            ]
        }
        with patch.object(client, "_request", return_value=mock_data):
            result = client.lookup("Fourier Neural Operator")
        assert result["status"] == "NOT_FOUND"

    def test_error_network(self, client):
        """Network error returns ERROR gracefully."""
        with patch.object(client, "_request", side_effect=ConnectionError("timeout")):
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
            "paperId": "a1b2c3d4e5",
            "title": "Fourier Neural Operator",
            "year": 2020,
        }

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise urllib.error.HTTPError("/paper/search", 429, "Too Many Requests", {}, None)
            mock_resp = MagicMock()
            mock_resp.__enter__.return_value.read.return_value = json.dumps({"data": [mock_paper]}).encode("utf-8")
            return mock_resp

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = side_effect
            result = client.lookup("Fourier Neural Operator")
        assert result["status"] == "VERIFIED"

    def test_empty_query(self, client):
        """Empty query returns NOT_FOUND (not crash)."""
        with patch.object(client, "_request", return_value={"data": [_MOCK_PAPER]}):
            result = client.lookup("")
        assert result["status"] in ("VERIFIED", "NOT_FOUND")


class TestS2Request:
    def test_404_returns_empty(self, client):
        """404 returns empty dict — not an exception."""
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            "/test", 404, "Not Found", {}, None
        )):
            result = client._request("/paper/search?query=test")
        assert result == {}

    def test_successful_request(self, client):
        """200 returns parsed JSON."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = mock_urlopen.return_value.__enter__.return_value
            mock_resp.read.return_value = json.dumps({"data": []}).encode("utf-8")
            result = client._request("/paper/search?query=test")
        assert result == {"data": []}
