#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filesystem-location gates for hfpapers-crawler.

Self-contained — zero dependency on hermes-verify or any internal package.

Gate legend:
  F05 — InstallPathGate: state resolves to the checkout in a source tree, and to
        the platform's user directories once installed — never inside the
        installation itself.
  F06 — NoAdHocStatePathGate: every state path goes through ``hfpapers.paths``
        instead of ad-hoc ``__file__`` arithmetic (the defect F05 guards against
        came back three times through new call sites).

Why F05 exists: `hfpapers` resolved its data directory as
``Path(__file__).parent.parent / "data"``. In a checkout that is the repository
root and everything works; installed from a wheel it is ``site-packages``, so
`hfpclawer store status` created ``<site-packages>/data/papers.db``. Read-only
or system-wide installs fail outright, and a user's library ends up hidden
inside the environment. The fix is "checkout first, XDG otherwise"; these tests
hold that line.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark_gate_f = pytest.mark.gate_f


class TestInstallPathGate:
    """F05: an installed package must never resolve state inside itself."""

    def test_checkout_mode_uses_the_repository(self):
        from hfpapers import paths

        root = paths.checkout_root()
        if root is None:  # running from an installed wheel — nothing to assert
            pytest.skip("not running from a source checkout")
        assert (root / "pyproject.toml").is_file()
        assert paths.state_root() == root
        assert paths.config_root() == root
        assert paths.data_dir() == root / "data"
        assert paths.config_path() == root / "config.yaml"

    def test_installed_mode_moves_to_user_directories(self, tmp_path, monkeypatch):
        from hfpapers import paths

        # Simulate site-packages: a package directory whose parent carries no
        # pyproject.toml, so it cannot be mistaken for a checkout.
        pkg_dir = tmp_path / "site-packages" / "hfpapers"
        pkg_dir.mkdir(parents=True)
        monkeypatch.delenv("HFPCLAWER_CHECKOUT_DIR", raising=False)
        monkeypatch.delenv("HFPCLAWER_STATE_DIR", raising=False)
        monkeypatch.delenv("HFPCLAWER_CONFIG_DIR", raising=False)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))

        assert paths.is_installed(pkg_dir)
        state = paths.state_root(pkg_dir)
        assert state == tmp_path / "xdg-data" / "hfpclawer"
        assert paths.data_dir(pkg_dir) == state / "data"
        assert paths.logs_dir(pkg_dir) == state / "logs"

        config = paths.config_root(pkg_dir)
        assert config == tmp_path / "xdg-config" / "hfpclawer"
        assert paths.config_path(pkg_dir) == config / "config.yaml"
        assert paths.local_config_path(pkg_dir) == config / "config.local.yaml"
        assert paths.env_path(pkg_dir) == config / ".env"

    def test_installed_mode_never_resolves_inside_the_package(self, tmp_path, monkeypatch):
        """The containment invariant — the actual regression this gate exists for."""
        from hfpapers import paths

        pkg_dir = tmp_path / "site-packages" / "hfpapers"
        pkg_dir.mkdir(parents=True)
        monkeypatch.delenv("HFPCLAWER_CHECKOUT_DIR", raising=False)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))

        install_root = tmp_path / "site-packages"
        for resolved in (
            paths.state_root(pkg_dir),
            paths.config_root(pkg_dir),
            paths.data_dir(pkg_dir),
            paths.logs_dir(pkg_dir),
            paths.config_path(pkg_dir),
        ):
            assert install_root not in resolved.parents, f"{resolved} is inside the installation"
            assert resolved != install_root

    def test_site_packages_is_never_a_checkout_even_with_pyproject(
        self, tmp_path, monkeypatch
    ):
        """A stray pyproject.toml must not turn an install into writable state."""
        from hfpapers import paths

        install_root = tmp_path / "site-packages"
        (install_root / "hfpapers").mkdir(parents=True)
        (install_root / "pyproject.toml").write_text('version = "0.0.0"\n', encoding="utf-8")
        monkeypatch.delenv("HFPCLAWER_CHECKOUT_DIR", raising=False)

        assert paths.checkout_root(install_root / "hfpapers") is None
        assert paths.is_installed(install_root / "hfpapers")

    def test_explicit_overrides_win(self, tmp_path, monkeypatch):
        from hfpapers import paths

        monkeypatch.setenv("HFPCLAWER_STATE_DIR", str(tmp_path / "state"))
        monkeypatch.setenv("HFPCLAWER_CONFIG_DIR", str(tmp_path / "conf"))
        assert paths.state_root() == tmp_path / "state"
        assert paths.data_dir() == tmp_path / "state" / "data"
        assert paths.config_path() == tmp_path / "conf" / "config.yaml"

    def test_xdg_defaults_when_unset(self, tmp_path, monkeypatch):
        from hfpapers import paths

        pkg_dir = tmp_path / "site-packages" / "hfpapers"
        pkg_dir.mkdir(parents=True)
        monkeypatch.delenv("HFPCLAWER_CHECKOUT_DIR", raising=False)
        monkeypatch.delenv("HFPCLAWER_STATE_DIR", raising=False)
        monkeypatch.delenv("HFPCLAWER_CONFIG_DIR", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))

        assert paths.state_root(pkg_dir) == tmp_path / "home" / ".local/share/hfpclawer"
        assert paths.config_root(pkg_dir) == tmp_path / "home" / ".config/hfpclawer"


class TestStateConsumers:
    """F05 (cont.): the consumers actually use the resolved root."""

    def test_db_path_follows_state_root(self, monkeypatch):
        from hfpapers import paths
        from hfpapers.paper_store import _db_path

        monkeypatch.delenv("HFPAPERS_DATA_DIR", raising=False)
        assert Path(_db_path()).parent == paths.data_dir()

    def test_db_path_env_override_still_wins(self, tmp_path, monkeypatch):
        from hfpapers.paper_store import _db_path

        monkeypatch.setenv("HFPAPERS_DATA_DIR", str(tmp_path / "elsewhere"))
        assert Path(_db_path()).parent == tmp_path / "elsewhere"

    def test_pool_log_and_transport_paths_live_under_state_root(self, monkeypatch):
        """Every state consumer agrees with ``paths`` in the *default* configuration.

        The suite harness points ``HFPAPERS_DATA_DIR`` at a temp dir (F08); the
        invariant below is about the no-override case, so clear it explicitly —
        pool/acquisition-log follow an absolute override while ``paths.data_dir()``
        never has, and mixing the two is what made this test red on configured
        machines.
        """
        from hfpapers import paths
        from hfpapers.arxiv_transport import acquisition_log_path
        from hfpapers.logger import LOG_DIR
        from hfpapers.pool import default_pool_path

        monkeypatch.delenv("HFPAPERS_DATA_DIR", raising=False)

        assert LOG_DIR == paths.logs_dir()
        assert default_pool_path().parent == paths.data_dir()
        assert acquisition_log_path().parent == paths.data_dir()


class TestNoAdHocStatePathGate:
    """F06: state paths resolve through hfpapers.paths, not __file__ arithmetic."""

    AD_HOC = re.compile(r"__file__[^\n]*parent\.parent|os\.path\.dirname\(\s*os\.path\.dirname\(\s*__file__")

    def _package_dirs(self):
        import hfpapers

        pkg_root = Path(hfpapers.__file__).resolve().parent
        dirs = [pkg_root]
        sibling = pkg_root.parent / "hfpclawer"
        if sibling.is_dir():
            dirs.append(sibling)
        return dirs

    def test_no_ad_hoc_state_paths_outside_paths_module(self):
        offenders = []
        for pkg_dir in self._package_dirs():
            for path in sorted(pkg_dir.rglob("*.py")):
                if path.name == "paths.py":
                    continue
                for lineno, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1
                ):
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        continue
                    if self.AD_HOC.search(line):
                        rel = path.relative_to(pkg_dir.parent)
                        offenders.append(f"{rel}:{lineno}: {stripped[:88]}")
        assert not offenders, (
            "state paths must go through hfpapers.paths (checkout first, XDG otherwise); "
            "ad-hoc __file__ arithmetic writes into site-packages when installed:\n"
            + "\n".join(offenders)
        )
