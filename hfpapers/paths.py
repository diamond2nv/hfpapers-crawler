#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ─── Filesystem locations ────────────────────────
# hfpapers/paths.py
"""Where hfpclawer keeps its state.

Two modes, decided by looking at where this package actually is:

* **checkout** — the package directory sits next to a ``pyproject.toml`` and not
  inside ``site-packages``/``dist-packages``: a source checkout or an editable
  install. State lives in the repository, exactly as it always has —
  ``config.yaml``, ``config.local.yaml``, ``.env``, ``data/``, ``logs/``.
* **installed** — anything else (a wheel installed by pip/uv). Writing inside the
  installation is wrong: it needs root on system installs, it is wiped with the
  environment, and the user's paper library ends up hidden in ``site-packages``.
  State moves to the platform's user directories (XDG on Linux/macOS):
  ``$XDG_CONFIG_HOME/hfpclawer`` for configuration, ``$XDG_DATA_HOME/hfpclawer``
  for the database, PDFs and logs.

Overrides, highest priority first: ``HFPCLAWER_STATE_DIR`` (one root for
everything), ``HFPCLAWER_CONFIG_DIR``, ``XDG_CONFIG_HOME``, ``XDG_DATA_HOME``.
``HFPAPERS_DATA_DIR`` is still honoured downstream by ``paper_store`` for the
database location specifically.

Nothing in this module creates directories or writes: it only answers "where".
"""

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent

_PACKAGE_MARKERS = ("site-packages", "dist-packages")


def _xdg(env_var: str, default: str) -> Path:
    """Resolve an XDG base directory, falling back to the conventional default."""
    value = os.environ.get(env_var) or ""
    if value.strip():
        return Path(value).expanduser()
    return Path.home() / default


def _looks_like_checkout(root: Path) -> bool:
    """True when *root* is a source checkout we may write state into."""
    if not (root / "pyproject.toml").is_file():
        return False
    if any(part in _PACKAGE_MARKERS for part in root.parts):
        return False
    return os.access(root, os.W_OK)


def checkout_root(pkg_dir: Path | None = None) -> Path | None:
    """The source checkout containing this package, or ``None`` when installed."""
    override = os.environ.get("HFPCLAWER_CHECKOUT_DIR")
    if override and override.strip():
        candidate = Path(override).expanduser()
        return candidate if _looks_like_checkout(candidate) else None
    root = (pkg_dir or PACKAGE_DIR).resolve().parent
    return root if _looks_like_checkout(root) else None


def config_root(pkg_dir: Path | None = None) -> Path:
    """Directory holding ``config.yaml`` / ``config.local.yaml`` / ``.env``."""
    override = os.environ.get("HFPCLAWER_CONFIG_DIR")
    if override and override.strip():
        return Path(override).expanduser()
    checkout = checkout_root(pkg_dir)
    if checkout is not None:
        return checkout
    return _xdg("XDG_CONFIG_HOME", ".config") / "hfpclawer"


def state_root(pkg_dir: Path | None = None) -> Path:
    """Directory holding ``data/`` and ``logs/`` (the working root)."""
    override = os.environ.get("HFPCLAWER_STATE_DIR")
    if override and override.strip():
        return Path(override).expanduser()
    checkout = checkout_root(pkg_dir)
    if checkout is not None:
        return checkout
    return _xdg("XDG_DATA_HOME", ".local/share") / "hfpclawer"


def data_dir(pkg_dir: Path | None = None) -> Path:
    """Default data directory — ``<state root>/data``."""
    return state_root(pkg_dir) / "data"


def pdf_dir(pkg_dir: Path | None = None) -> Path:
    """Canonical PDF directory: ``<data>/pdfs``.

    One accessor, because the alternative was measured: two directories — ``<repo>/pdfs`` and
    ``<data>/pdfs`` — held 62 PDFs between them, and ``hfpclawer fetch`` wrote to the one the store,
    the config and the audit do not look at.  A record could therefore be "downloaded" and stay
    invisible to every later check (docs/AUDIT_CRITIQUE.md §8).
    """
    return data_dir(pkg_dir) / "pdfs"


def logs_dir(pkg_dir: Path | None = None) -> Path:
    """Default log directory — ``<state root>/logs``."""
    return state_root(pkg_dir) / "logs"


def config_path(pkg_dir: Path | None = None) -> Path:
    """Tracked-config location for this installation mode."""
    return config_root(pkg_dir) / "config.yaml"


def local_config_path(pkg_dir: Path | None = None) -> Path:
    """Gitignored personal-overlay location for this installation mode."""
    return config_root(pkg_dir) / "config.local.yaml"


def env_path(pkg_dir: Path | None = None) -> Path:
    """``.env`` location for this installation mode."""
    return config_root(pkg_dir) / ".env"


def peer_roots() -> list[Path]:
    """Every peer repository path declared by the environment, in order.

    Sources: ``HFPCLAWER_PEER_REPOS`` (JSON object, or comma-separated
    ``name=path`` pairs) and any ``HFPCLAWER_PEER_<NAME>`` variables. Deduplicated,
    non-existent paths dropped.
    """
    import json

    found: list[Path] = []
    blob = os.environ.get("HFPCLAWER_PEER_REPOS") or ""
    if blob.strip():
        mapping: dict = {}
        try:
            parsed = json.loads(blob)
            if isinstance(parsed, dict):
                mapping = parsed
        except ValueError:
            for pair in blob.split(","):
                if "=" in pair:
                    name, value = pair.split("=", 1)
                    mapping[name.strip()] = value.strip()
        for value in mapping.values():
            if value:
                found.append(Path(str(value)).expanduser())
    for key, value in os.environ.items():
        if key.startswith("HFPCLAWER_PEER_") and key != "HFPCLAWER_PEER_REPOS" and value.strip():
            found.append(Path(value).expanduser())

    unique: list[Path] = []
    for path in found:
        if path not in unique and path.exists():
            unique.append(path)
    return unique


def peer_repo(name: str, root: Path | None = None) -> Path | None:
    """Locate a *peer* repository (a sibling project this one can import from).

    Peer names and locations are environment data, never constants: publishing a
    repository must not disclose the names of the private projects sitting next to
    it. Configure with ``HFPCLAWER_PEER_REPOS`` (a JSON object of name → path) or
    per-peer ``HFPCLAWER_PEER_<NAME>``; ``.env`` is the intended place, since it is
    gitignored. Without configuration this returns ``None`` and callers fall back
    to an explicitly passed path.
    """
    import json

    key = f"HFPCLAWER_PEER_{name.upper().replace('-', '_')}"
    direct = os.environ.get(key)
    if direct and direct.strip():
        return Path(direct).expanduser()

    blob = os.environ.get("HFPCLAWER_PEER_REPOS")
    if blob and blob.strip():
        try:
            mapping = json.loads(blob)
        except ValueError:
            mapping = {}
        if isinstance(mapping, dict) and mapping.get(name):
            return Path(str(mapping[name])).expanduser()

    if root is not None:
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def is_installed(pkg_dir: Path | None = None) -> bool:
    """True when this code is running from an installed wheel, not a checkout."""
    return checkout_root(pkg_dir) is None
