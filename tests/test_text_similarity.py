#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for hfpclawer/_text_similarity.py — title normalization and similarity.

Adapted from academic-research-skills (CC BY-NC 4.0).
"""

from hfpclawer._text_similarity import _normalize_title, exact_match, title_similarity


class TestNormalizeTitle:
    def test_lowercases(self):
        assert _normalize_title("Foo Bar Baz") == "foo bar baz"

    def test_punctuation_stripped(self):
        assert _normalize_title("Foo,  Bar... Baz!") == "foo bar baz"

    def test_acronym_dots_collapse(self):
        """Dots are stripped by regex, acronym letters merge (no spaces between)."""
        assert _normalize_title("R.A.G.") == "rag"

    def test_empty_string(self):
        assert _normalize_title("") == ""

    def test_whitespace_only(self):
        assert _normalize_title("   \t\n  ") == ""

    def test_already_normalized(self):
        assert _normalize_title("attention is all you need") == "attention is all you need"

    def test_hyphens_preserved(self):
        """Hyphen is a word character (\\w matches [a-zA-Z0-9_])."""
        result = _normalize_title("Pre-trained Model")
        assert "pre" in result and "trained" in result


class TestTitleSimilarity:
    def test_acronym_clears_threshold(self):
        assert title_similarity("R.A.G.", "RAG") >= 0.70

    def test_punctuation_stripped_before_similarity(self):
        sim = title_similarity(
            "Attention Is All You Need: A Transformers Story",
            "attention is all you need a transformers story",
        )
        assert sim > 0.95

    def test_identical_strings_score_one(self):
        assert title_similarity("foo bar", "foo bar") == 1.0

    def test_completely_different_scores_low(self):
        assert title_similarity("alpha beta gamma", "xyz qrs uvw") < 0.3


class TestExactMatch:
    def test_exact_identical(self):
        assert exact_match("Attention Is All You Need", "Attention Is All You Need")

    def test_case_difference(self):
        assert exact_match("FOO BAR", "foo bar")

    def test_punctuation_difference(self):
        assert exact_match("Foo, Bar!", "Foo Bar")

    def test_different_strings_not_exact(self):
        assert not exact_match("alpha", "beta")
