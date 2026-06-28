#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for hfpclawer.import_paper — resolver + importer."""



from hfpclawer.import_paper.resolver import (
    _resolve_arxiv,
    _resolve_doi,
    resolve_identifier,
)

# ════════════════════════════════════════════
# Resolver tests
# ════════════════════════════════════════════

class TestResolveArxiv:
    def test_bare_id(self):
        """Bare arXiv ID is accepted."""
        r = _resolve_arxiv("2501.01934")
        assert r.ok
        assert r.normalized == "2501.01934"
        assert r.source == "arxiv"

    def test_bare_id_with_version(self):
        """Version suffix is stripped."""
        r = _resolve_arxiv("2501.01934v2")
        assert r.ok
        assert r.normalized == "2501.01934"

    def test_arxiv_abs_url(self):
        """arxiv.org/abs/ URL."""
        r = _resolve_arxiv("https://arxiv.org/abs/2501.01934")
        assert r.ok
        assert r.normalized == "2501.01934"

    def test_arxiv_abs_url_with_version(self):
        """arxiv.org/abs/ URL with version."""
        r = _resolve_arxiv("https://arxiv.org/abs/2501.01934v3")
        assert r.ok
        assert r.normalized == "2501.01934"

    def test_arxiv_pdf_url(self):
        """arxiv.org/pdf/ URL."""
        r = _resolve_arxiv("https://arxiv.org/pdf/2501.01934.pdf")
        assert r.ok
        assert r.normalized == "2501.01934"

    def test_arxiv_http_url(self):
        """http (not https) works too."""
        r = _resolve_arxiv("http://arxiv.org/abs/2501.01934")
        assert r.ok
        assert r.normalized == "2501.01934"

    def test_non_arxiv_string(self):
        """Random string returns error."""
        r = _resolve_arxiv("some random text")
        assert not r.ok
        assert "not_arxiv" in r.error


class TestResolveDoi:
    def test_standard_doi(self):
        """Standard DOI is accepted."""
        r = _resolve_doi("10.1016/j.jcp.2025.114432")
        assert r.ok
        assert r.normalized == "10.1016/j.jcp.2025.114432"
        assert r.source == "doi"

    def test_doi_with_suffix(self):
        """DOI at end of sentence (trailing period stripped)."""
        r = _resolve_doi("See doi: 10.1038/s41586-024-07123-5.")
        assert r.ok
        assert r.normalized == "10.1038/s41586-024-07123-5"

    def test_doi_url(self):
        """DOI.org URL. The DOI resolver should match the DOI inside."""
        r = _resolve_doi("https://doi.org/10.1103/PhysRevLett.130.100801")
        assert r.ok
        assert r.normalized == "10.1103/PhysRevLett.130.100801"

    def test_not_doi(self):
        """Plain text returns error."""
        r = _resolve_doi("a random string")
        assert not r.ok


class TestResolveIdentifier:
    def test_arxiv_id(self):
        """arXiv ID gets resolved."""
        r = resolve_identifier("2501.01934")
        assert r.ok
        assert r.source == "arxiv"

    def test_arxiv_url(self):
        """arXiv URL gets resolved."""
        r = resolve_identifier("https://arxiv.org/abs/2501.01934v2")
        assert r.ok
        assert r.source == "arxiv"
        assert r.normalized == "2501.01934"

    def test_doi(self):
        """DOI gets resolved."""
        r = resolve_identifier("10.1016/j.jcp.2025.114432")
        assert r.ok
        assert r.source == "doi"
        assert r.normalized == "10.1016/j.jcp.2025.114432"

    def test_empty_string(self):
        """Empty input returns error."""
        r = resolve_identifier("")
        assert not r.ok
        assert "empty" in r.error

    def test_none_input(self):
        """None input returns error."""
        r = resolve_identifier("   ")
        assert not r.ok
        assert "empty" in r.error

    def test_unrecognised(self):
        """Gibberish returns error."""
        r = resolve_identifier("this is not a paper identifier at all")
        assert not r.ok
        assert "unrecognised" in r.error


# ════════════════════════════════════════════
# Importer tests (mock-based)
# ════════════════════════════════════════════

class TestImportResult:
    def test_ok_property(self):
        """No error and non-empty id → ok. (placeholder)"""
        pass


# ════════════════════════════════════════════
# Test the docstring examples
# ════════════════════════════════════════════

class TestDocstrings:
    def test_resolver_docstring_examples(self):
        """Verify docstring examples work."""
        r = resolve_identifier("2501.01934")
        assert r.ok
        assert r.source == "arxiv"

        r = resolve_identifier("10.1016/j.jcp.2025.114432")
        assert r.ok
        assert r.source == "doi"

        r = resolve_identifier("https://arxiv.org/abs/2501.01934")
        assert r.ok
        assert r.source == "arxiv"
