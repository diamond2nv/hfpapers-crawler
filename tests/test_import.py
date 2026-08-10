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


class TestFetchArxivMeta:
    """Regression test for v0.15.2: metadata must be assigned back,
    not merely logged to steps (previously title fell back to arXiv ID)."""

    def _make_result(self, aid="2504.19413"):
        from hfpclawer.import_paper.importer import ImportResult

        return ImportResult(arxiv_id=aid)

    def test_title_abstract_year_assigned(self, monkeypatch):
        """_fetch_arxiv_meta populates result.title/.abstract/.year."""
        sample_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2504.19413v1</id>
    <title>Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory</title>
    <summary>Large Language Models (LLMs) have demonstrated remarkable prowess.</summary>
    <published>2025-04-25T17:59:48Z</published>
  </entry>
</feed>"""

        class FakeResp:
            def read(self):
                return sample_xml

        class FakeUrlopen:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return FakeResp()

            def __exit__(self, *a):
                return False

        import hfpclawer.import_paper.importer as imp

        monkeypatch.setattr(imp.urllib.request, "urlopen", FakeUrlopen)
        result = self._make_result()
        imp._fetch_arxiv_meta(result)

        assert result.title == (
            "Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory"
        )
        assert "remarkable prowess" in result.abstract
        assert result.year == 2025

    def test_fetch_failure_keeps_empty_meta(self, monkeypatch):
        """On API failure, result stays empty (best-effort, non-fatal)."""

        def boom(*a, **kw):
            raise OSError("network down")

        import hfpclawer.import_paper.importer as imp

        monkeypatch.setattr(imp.urllib.request, "urlopen", boom)
        result = self._make_result()
        imp._fetch_arxiv_meta(result)

        assert result.title == ""
        assert result.abstract == ""
        assert result.year == 0
        assert any("failed" in s for s in result.steps)


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
