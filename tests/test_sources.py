#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for sources module — multi-source search + arXiv ID extraction + dedup"""

from hfpapers.sources import (
    ARXIV_ID_RE,
    SourcePaper,
    _safe_field,
    deduplicate,
    get_enabled_sources,
)


class TestArxivIdRegex:
    def test_match_standard(self):
        m = ARXIV_ID_RE.search("2301.11167")
        assert m is not None
        assert m.group(1) == "2301.11167"

    def test_match_with_version(self):
        m = ARXIV_ID_RE.search("2301.11167v3")
        assert m is not None
        assert m.group(1) == "2301.11167"

    def test_match_5_digit(self):
        m = ARXIV_ID_RE.search("2301.12345")
        assert m is not None

    def test_match_in_url(self):
        m = ARXIV_ID_RE.search("https://arxiv.org/abs/2301.11167v2")
        assert m is not None
        assert m.group(1) == "2301.11167"

    def test_no_match(self):
        m = ARXIV_ID_RE.search("not-an-arxiv-id")
        assert m is None

    def test_no_match_short(self):
        m = ARXIV_ID_RE.search("123.456")
        assert m is None


class TestSafeField:
    def test_plain_string(self):
        assert _safe_field({"title": "Paper Title"}, "title") == "Paper Title"

    def test_nested_value_dict(self):
        assert _safe_field({"title": {"value": "Nested Title"}}, "title") == "Nested Title"

    def test_nested_content_dict(self):
        assert (
            _safe_field({"abstract": {"content": "Abstract text"}}, "abstract") == "Abstract text"
        )

    def test_missing_key(self):
        assert _safe_field({"other": "value"}, "nonexistent") == ""


class TestDeduplicate:
    def test_no_duplicates(self):
        papers = [
            SourcePaper(arxiv_id="2301.00001", title="A"),
            SourcePaper(arxiv_id="2301.00002", title="B"),
        ]
        result = deduplicate(papers)
        assert len(result) == 2

    def test_duplicates_removed(self):
        papers = [
            SourcePaper(arxiv_id="2301.00001", title="A"),
            SourcePaper(arxiv_id="2301.00001", title="A duplicate"),
            SourcePaper(arxiv_id="2301.00002", title="B"),
        ]
        result = deduplicate(papers)
        assert len(result) == 2
        assert result[0].title == "A"

    def test_empty_list(self):
        assert deduplicate([]) == []


class TestGetEnabledSources:
    def test_returns_list(self, test_env):
        sources = get_enabled_sources()
        assert len(sources) > 0
        assert all(hasattr(s, "search") for s in sources)


class TestSourcePaper:
    def test_defaults(self):
        p = SourcePaper()
        assert p.arxiv_id == ""
        assert p.reviews == []
        assert p.source == ""
