#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for hfpapers.sources.github_ingest"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hfpapers.source_adapters.github_ingest import (
    GitHubSource,
    parse_github_url,
)


class TestParseGitHubUrl:
    """parse_github_url should handle all common URL formats"""

    def test_https_url(self):
        assert parse_github_url("https://github.com/user/repo") == ("user", "repo")

    def test_https_url_with_git_suffix(self):
        assert parse_github_url("https://github.com/user/repo.git") == ("user", "repo")

    def test_ssh_url(self):
        assert parse_github_url("git@github.com:user/repo.git") == ("user", "repo")

    def test_bare_format(self):
        assert parse_github_url("user/repo") is None  # not a URL

    def test_nested_path(self):
        r = parse_github_url("https://github.com/dobriban/BH")
        assert r == ("dobriban", "BH")

    def test_raw_subdomain(self):
        r = parse_github_url("https://raw.githubusercontent.com/user/repo/main/README.md")
        assert r is not None
        assert r == ("user", "repo")


class TestGitHubSource:
    """GitHubSource adapter — mocked tests"""

    @patch("hfpapers.source_adapters.github_ingest._github_api_request")
    def test_fetch_with_full_data(self, mock_api):
        """fetch should return SourceDocument with metadata from API"""
        mock_api.return_value = {
            "full_name": "testowner/testrepo",
            "html_url": "https://github.com/testowner/testrepo",
            "description": "A test repository",
            "language": "Python",
            "stargazers_count": 42,
            "forks_count": 7,
            "topics": ["testing", "python"],
            "created_at": "2023-01-15T00:00:00Z",
            "owner": {"login": "testowner"},
            "license": {"spdx_id": "MIT"},
        }

        source = GitHubSource()
        # Mock _fetch_readme and _fetch_deepwiki to avoid network calls
        source._fetch_readme = MagicMock(return_value="# Test Repo\n\nThis is a test.")
        source._fetch_deepwiki = MagicMock(return_value="Architecture summary.")

        doc = source.fetch("testowner/testrepo")
        assert doc is not None
        assert doc.id == "gh:testowner/testrepo"
        assert doc.title == "testowner/testrepo"
        assert doc.source == "gh_ingest"
        assert doc.confidence == 0.8  # has deepwiki
        assert "Architecture summary" in doc.content
        assert "This is a test." in doc.content
        assert doc.metadata["stars"] == 42
        assert doc.metadata["language"] == "Python"
        assert doc.metadata["license"] == "MIT"
        assert doc.metadata["has_deepwiki"] is True

    @patch("hfpapers.source_adapters.github_ingest._github_api_request")
    def test_fetch_api_fallback_to_raw_readme(self, mock_api):
        """When API fails, should return README-only document"""
        mock_api.return_value = None  # API fails

        source = GitHubSource()
        source._fetch_readme = MagicMock(return_value="# README Only\n\nAPI was down.")

        doc = source.fetch("testowner/testrepo")
        assert doc is not None
        assert doc.confidence == 0.5  # fallback
        assert doc.metadata.get("fallback") is True
        assert "API was down." in doc.content

    @patch("hfpapers.source_adapters.github_ingest._github_api_request")
    def test_fetch_invalid_repo_id(self, mock_api):
        """Invalid repo_id format should return None"""
        source = GitHubSource()
        doc = source.fetch("invalid-format-without-slash")
        assert doc is None  # invalid format, no error
        mock_api.assert_not_called()

    @patch("hfpapers.source_adapters.github_ingest._github_api_request")
    def test_search_returns_source_documents(self, mock_api):
        """search should return list of SourceDocuments"""
        mock_api.return_value = {
            "items": [
                {
                    "full_name": "repo1/one",
                    "html_url": "https://github.com/repo1/one",
                    "description": "First repo",
                    "stargazers_count": 100,
                    "language": "Python",
                    "created_at": "2024-01-01T00:00:00Z",
                    "owner": {"login": "repo1"},
                    "topics": ["ai"],
                    "forks_count": 5,
                },
                {
                    "full_name": "repo2/two",
                    "html_url": "https://github.com/repo2/two",
                    "language": "Rust",
                    "created_at": "2023-06-01T00:00:00Z",
                    "owner": {"login": "repo2"},
                    "topics": [],
                    "forks_count": 2,
                },
            ]
        }

        source = GitHubSource()
        source._fetch_readme = MagicMock(return_value="README")
        source._fetch_deepwiki = MagicMock(return_value="")

        docs = source.search("test query", limit=5)
        assert len(docs) == 2
        assert docs[0].id == "gh:repo1/one"
        assert docs[1].id == "gh:repo2/two"
        assert docs[0].title == "repo1/one"
        assert docs[1].title == "repo2/two"
        assert docs[0].tags == ["ai"]
        assert docs[1].tags == []

    def test_to_search_result(self):
        """to_search_result should produce valid SearchResult"""
        source = GitHubSource()
        doc = source.fetch  # Just use a manual doc

        from hfpapers.source_adapters import SourceDocument
        doc = SourceDocument(
            id="gh:user/repo",
            title="user/repo",
            abstract="Nice repo",
            content="Full README...",
            source="gh_ingest",
            source_url="https://github.com/user/repo",
            code_url="https://github.com/user/repo",
            confidence=0.8,
        )
        sr = source.to_search_result(doc)
        assert sr.title == "user/repo"
        assert sr.source == "gh_ingest"
        assert sr.code_url == "https://github.com/user/repo"
        assert sr.confidence == 0.8
