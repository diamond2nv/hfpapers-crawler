"""Gates for the public cut: the source tree and the public-only paths.

Why this test file exists (two gates, both paid for):

1. **public-only paths** — `git checkout <dev> -- .` (the recut's sync step) copies the *content*
   of paths that exist in both trees and never deletes anything.  Dead files therefore survive
   every recut on the public line -- on 2026-09-21 three stale requirement lists (including a
   188-line freeze of the v0.1.3 environment) kept all 55 open Dependabot advisories alive through
   several recuts.  `public_only_paths` is the gate that refuses the cut instead.

2. **the source tree must be the release tag** — a public cut snapshots a release, not whatever the
   development branch has reached.  The gate added 2026-09-21 only checked that a dev tag *exists*;
   `--source` still defaulted to `"main"`, so the default cut kept taking the branch tip.  Measured
   2026-09-23 and fixed here: `resolve_source_ref` defaults to `vVERSION`, and an operator override
   is reported as such (`source_is_release`).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "recut-public.py"
    if not path.is_file():
        pytest.skip("scripts/recut-public.py is not present in this checkout")
    spec = importlib.util.spec_from_file_location("recut_public", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture()
def repo_with_stale_file(tmp_path: Path) -> Path:
    """A one-repo stand-in: branch `dev` is the source tree, HEAD is the public tree."""
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "shared.txt").write_text("same on both lines\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "base: shared.txt")
    _git(work, "branch", "dev")  # the development line stops here
    (work / "stale.txt").write_text("public-only leftover\n", encoding="utf-8")
    (work / "requirements").mkdir()
    (work / "requirements" / "requirements_all_0.1.3.txt").write_text("aiohttp==3.8.0\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "public: add files the dev line never had")
    return work


def test_detects_public_only_paths(repo_with_stale_file: Path) -> None:
    module = _load_module()
    # `repo` is the tree the source ref is read from; production passes the real repo, the test its own
    found = module.public_only_paths(repo_with_stale_file, "dev", [], repo=repo_with_stale_file)
    assert found == ["requirements/requirements_all_0.1.3.txt", "stale.txt"], found


def test_synced_paths_are_not_reported(repo_with_stale_file: Path) -> None:
    module = _load_module()
    # `repo` is the tree the source ref is read from; production passes the real repo, the test its own
    found = module.public_only_paths(repo_with_stale_file, "dev", [], repo=repo_with_stale_file)
    assert "shared.txt" not in found  # present on both lines -> not the gate's business


def test_allowlist_suppresses_exact_and_glob(repo_with_stale_file: Path) -> None:
    module = _load_module()
    assert module.public_only_paths(repo_with_stale_file, "dev", ["stale.txt"], repo=repo_with_stale_file) == [
        "requirements/requirements_all_0.1.3.txt"
    ]
    assert module.public_only_paths(
        repo_with_stale_file, "dev", ["*.txt", "requirements/**"], repo=repo_with_stale_file
    ) == []


def test_clean_public_tree_reports_nothing(tmp_path: Path) -> None:
    module = _load_module()
    work = tmp_path / "clean"
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "a.txt").write_text("x\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "only one commit")
    _git(work, "branch", "dev")
    assert module.public_only_paths(work, "dev", [], repo=work) == []


def test_dev_release_tag_absent_for_an_unreleased_version(repo_with_stale_file: Path) -> None:
    """A public cut may only snapshot a release: no dev tag -> no cut (measured 2026-09-21)."""
    module = _load_module()
    assert module.dev_release_tag("0.21.0", repo=repo_with_stale_file) == ""


def test_dev_release_tag_found_when_the_dev_line_tagged_it(repo_with_stale_file: Path) -> None:
    module = _load_module()
    _git(repo_with_stale_file, "tag", "-a", "v0.21.0", "-m", "release", "dev")
    assert module.dev_release_tag("0.21.0", repo=repo_with_stale_file) == "v0.21.0"
    assert module.dev_release_tag("0.23.0", repo=repo_with_stale_file) == ""


def test_source_defaults_to_the_release_tag() -> None:
    """Regression (2026-09-23): the default cut must snapshot the release, not a branch tip.

    `--source` used to default to "main", so the *default* invocation cut from the branch tip while
    the tag gate happily passed (the tag existed -- the tree just didn't come from it).  That is the
    same shape as the retracted 0.21.0 cut.
    """
    module = _load_module()
    assert module.resolve_source_ref("0.21.0") == ("v0.21.0", "tag")


def test_source_overrides_are_marked_as_such() -> None:
    module = _load_module()
    assert module.resolve_source_ref("0.21.0", source="main") == ("main", "branch")
    assert module.resolve_source_ref("0.21.0", source="main", source_ref="v0.21.0^{}") == (
        "v0.21.0^{}",
        "explicit-ref",
    )
    assert module.resolve_source_ref("0.21.0", source_ref="v0.19.0^{}") == ("v0.19.0^{}", "explicit-ref")


def test_source_is_release_compares_commits(repo_with_stale_file: Path) -> None:
    """`source_is_release` is what turns "a tag exists" into "the tree *is* that release"."""
    module = _load_module()
    work = repo_with_stale_file
    _git(work, "tag", "-a", "v0.21.0", "-m", "release", "dev")  # the tag points at branch `dev`
    assert module.source_is_release("0.21.0", "v0.21.0", repo=work) is True
    assert module.source_is_release("0.21.0", "v0.21.0^{}", repo=work) is True
    assert module.source_is_release("0.21.0", "HEAD", repo=work) is False  # public tip moved past it
    assert module.source_is_release("0.21.0", "no-such-ref", repo=work) is False
    assert module.source_is_release("0.23.0", "HEAD", repo=work) is False  # no tag -> never a release


def test_ref_resolves_and_commit_of(repo_with_stale_file: Path) -> None:
    """The preflight's fast failure on a typo'd --source-ref leans on these two."""
    module = _load_module()
    work = repo_with_stale_file
    _git(work, "tag", "-a", "v0.21.0", "-m", "release", "dev")
    assert module.ref_resolves("v0.21.0", repo=work) is True
    assert module.ref_resolves("no-such-ref", repo=work) is False
    assert module.commit_of("v0.21.0", repo=work) == module.commit_of("dev", repo=work)
    assert module.commit_of("no-such-ref", repo=work) == ""


def test_cli_help_advertises_the_release_tag_default() -> None:
    """The operator-visible contract: `--source` is an override, the default is the release tag."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "recut-public.py"
    if not script.is_file():
        pytest.skip("scripts/recut-public.py is not present in this checkout")
    out = subprocess.run(
        [sys.executable, str(script), "--help"], capture_output=True, text=True, check=True
    )
    assert "release tag" in out.stdout
    assert "default: main" not in out.stdout
