"""Config loading: base config.yaml + optional gitignored config.local.yaml overlay.

Rationale: config.yaml is tracked and public. It carries environment-specific and
third-party data (real researcher names, ORCIDs, local paths) that must not be
published. The overlay lets the public file hold structure only, while the real
values live in config.local.yaml, which is gitignored.
"""

import pytest


@pytest.fixture(autouse=True)
def _reset_config_cache():
    """load_config() caches at module level; reset it around every test here."""
    import hfpapers.config as config

    config._config_cache = None
    yield
    config._config_cache = None


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_local_config_overlays_base(tmp_path, monkeypatch):
    import hfpapers.config as config

    base = _write(tmp_path / "config.yaml", "search:\n  enabled: [hf_cli]\n  max_per_dim: 30\n")
    local = _write(tmp_path / "config.local.yaml", "search:\n  enabled: [europepmc, biorxiv]\n")
    monkeypatch.setenv("_TEST_HFPAPERS_CONFIG", base)
    monkeypatch.setenv("_TEST_HFPAPERS_LOCAL_CONFIG", local)

    config.load_config(reload=True)
    assert config.get("search.enabled") == ["europepmc", "biorxiv"]  # overridden
    assert config.get("search.max_per_dim") == 30  # sibling key survives


def test_local_config_absent_is_noop(tmp_path, monkeypatch):
    import hfpapers.config as config

    base = _write(tmp_path / "config.yaml", "search:\n  enabled: [hf_cli]\n")
    monkeypatch.setenv("_TEST_HFPAPERS_CONFIG", base)
    monkeypatch.delenv("_TEST_HFPAPERS_LOCAL_CONFIG", raising=False)

    config.load_config(reload=True)
    assert config.get("search.enabled") == ["hf_cli"]


def test_local_config_merges_nested_structures(tmp_path, monkeypatch):
    import hfpapers.config as config

    base = _write(
        tmp_path / "config.yaml",
        "stepping:\n  filter_authors: []\n  layers:\n  - name: demo\n",
    )
    local = _write(
        tmp_path / "config.local.yaml",
        "stepping:\n  filter_authors:\n  - Doe J\n  orcid_seeds:\n  - 0000-0000-0000-0000\n",
    )
    monkeypatch.setenv("_TEST_HFPAPERS_CONFIG", base)
    monkeypatch.setenv("_TEST_HFPAPERS_LOCAL_CONFIG", local)

    config.load_config(reload=True)
    assert config.get("stepping.filter_authors") == ["Doe J"]
    assert config.get("stepping.orcid_seeds") == ["0000-0000-0000-0000"]
    assert config.get("stepping.layers") == [{"name": "demo"}]  # untouched subtree


def test_overlay_does_not_leak_into_missing_base(tmp_path, monkeypatch):
    """A missing base file still yields the built-in defaults (no overlay-only config)."""
    import hfpapers.config as config

    local = _write(tmp_path / "config.local.yaml", "search:\n  enabled: [europepmc]\n")
    monkeypatch.setenv("_TEST_HFPAPERS_CONFIG", str(tmp_path / "does-not-exist.yaml"))
    monkeypatch.setenv("_TEST_HFPAPERS_LOCAL_CONFIG", local)

    config.load_config(reload=True)
    assert config.get("search.max_per_dim") == 50  # built-in default branch
