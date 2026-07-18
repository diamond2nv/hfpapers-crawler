"""Tests for hfpapers.sources registry"""

from hfpapers.source_adapters import get_source, list_sources, BaseSource


class TestSourceRegistry:

    def test_list_contains_gh_ingest(self):
        sources = list_sources()
        assert "gh_ingest" in sources

    def test_get_gh_ingest_returns_instance(self):
        source = get_source("gh_ingest")
        assert source is not None
        assert isinstance(source, BaseSource)
        assert source.name == "gh_ingest"

    def test_get_unknown_source_returns_none(self):
        source = get_source("nonexistent_source")
        assert source is None

    def test_registry_is_ordered(self):
        sources = list_sources()
        assert sources == sorted(sources)
