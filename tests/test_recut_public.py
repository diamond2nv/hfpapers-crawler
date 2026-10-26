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


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    )


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


# ── the two modes (2026-10-26) ────────────────────────────────────────────────
# The gate used to conflate "public push" with "public release": one version rule refused both.
# Continuous sync needs the two split apart — the release rule stays for releases, traceability
# and monotonicity stay for both.


def test_release_version_rule_is_odd_x_only() -> None:
    module = _load_module()
    assert module.is_public_release_version("0.19.0") is True
    assert module.is_public_release_version("0.21.0") is True
    assert module.is_public_release_version("0.20.0") is False  # even x
    assert module.is_public_release_version("0.20.3") is False  # patch
    assert module.is_public_release_version("0.19.1") is False  # dev-line fix release
    assert module.is_public_release_version("1.21.0") is False  # not this project's shape


def test_sync_mode_accepts_a_patch_version() -> None:
    """A dev fix release may be synced (continuous commits) even though it can never be released."""
    module = _load_module()
    assert module.judge_request("sync", "0.20.3", "0.19.0", "v0.20.3") == ""
    assert module.judge_request("sync", "0.20.0", "0.19.0", "v0.20.0") == ""


def test_release_mode_refuses_a_patch_version_and_points_at_sync() -> None:
    module = _load_module()
    refusal = module.judge_request("release", "0.20.3", "0.19.0", "v0.20.3")
    assert refusal
    assert "--mode sync" in refusal


def test_both_modes_require_a_development_tag() -> None:
    """Traceability is not a release-only property: a sync snapshots a release too."""
    module = _load_module()
    assert module.judge_request("sync", "0.20.3", "", "") != ""
    assert module.judge_request("release", "0.21.0", "", "") != ""
    assert module.judge_request("sync", "0.20.3", "0.19.0", "v0.20.3") == ""


def test_high_water_blocks_a_backwards_push() -> None:
    """The public tree must describe one number with one tree — so it only moves forward."""
    module = _load_module()
    assert module.judge_request("sync", "0.19.9", "0.20.3", "v0.19.9") != ""
    assert module.judge_request("release", "0.19.0", "0.19.0", "v0.19.0") != ""
    assert module.judge_request("sync", "0.20.4", "0.20.3", "v0.20.4") == ""
    assert module.judge_request("release", "0.21.0", "0.20.3", "v0.21.0") == ""


def test_resync_at_the_same_version_is_refused_with_a_way_out() -> None:
    """A second sync at the same number would put two trees behind one version (measured 2026-10-26)."""
    module = _load_module()
    refusal = module.judge_request("sync", "0.20.1", "0.20.1", "v0.20.1")
    assert refusal, "a re-sync at the high-water version must be refused"
    assert "release.sh" in refusal, "the message must name the way forward, not just the rule"


def test_sync_refuses_a_stale_source_unless_overridden() -> None:
    """The mirror-image trap: older dev content behind a *higher* public number."""
    module = _load_module()
    refusal = module.judge_request(
        "sync", "0.19.9", "0.19.0", "v0.19.9", newest_dev="v0.19.16"
    )
    assert refusal and "0.19.16" in refusal
    assert (
        module.judge_request(
            "sync", "0.19.9", "0.19.0", "v0.19.9", newest_dev="v0.19.16", allow_stale=True
        )
        == ""
    )
    # syncing the newest development release is the normal case
    assert module.judge_request("sync", "0.19.16", "0.19.0", "v0.19.16", newest_dev="v0.19.16") == ""


def test_newest_dev_tag_reads_development_tags(tmp_path: Path) -> None:
    module = _load_module()
    work = tmp_path / "dev-line"
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "a.txt").write_text("x\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "base")
    _git(work, "branch", "-M", "main")
    _git(work, "tag", "v0.19.2")
    _git(work, "tag", "v0.19.10")
    _git(work, "tag", "public-v0.20.9")  # a public-line tag must not be mistaken for a dev release
    assert module.newest_dev_tag(repo=work) == "v0.19.10"


def test_public_high_water_reads_tags_and_sync_trailers(tmp_path: Path) -> None:
    module = _load_module()
    work = tmp_path / "public-line"
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "a.txt").write_text("x\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "v0.19.0: public snapshot")
    _git(work, "tag", "-a", "public-v0.19.0", "-m", "release")
    _git(work, "branch", "public")
    assert module.public_high_water("public", repo=work) == ("0.19.0", "tag public-v0.19.0")

    # a sync commit carries the mark in a trailer, which is what makes the advance readable
    _git(work, "checkout", "-q", "public")
    (work / "a.txt").write_text("y\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(
        work,
        "commit",
        "-qm",
        "sync(public): v0.20.3 — not a release",
        "-m",
        "Public-Sync: v0.20.3",
    )
    assert module.public_high_water("public", repo=work) == ("0.20.3", "trailer Public-Sync")


def test_public_high_water_is_empty_without_any_mark(tmp_path: Path) -> None:
    module = _load_module()
    work = tmp_path / "bare"
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "a.txt").write_text("x\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "base")
    assert module.public_high_water("HEAD", repo=work) == ("", "")


def test_cli_help_advertises_the_sync_mode() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "recut-public.py"
    if not script.is_file():
        pytest.skip("scripts/recut-public.py is not present in this checkout")
    out = subprocess.run(
        [sys.executable, str(script), "--help"], capture_output=True, text=True, check=True
    )
    assert "--mode" in out.stdout
    assert "sync" in out.stdout


def test_dispose_worktree_removes_the_registration(tmp_path: Path) -> None:
    """A deleted directory is not a removed worktree (measured 2026-10-26).

    ``shutil.rmtree`` left ``.git/worktrees/<name>`` behind, so the branch stayed marked as
    checked out and the next ``git worktree add … <branch>`` failed with "already checked out".
    """
    module = _load_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    repo.joinpath("a.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "branch", "-M", "main")
    _git(repo, "branch", "public")  # must NOT be checked out here, or worktree add refuses

    scratch = tmp_path / "scratch"
    _git(repo, "worktree", "add", "-q", str(scratch), "public")
    module.dispose_worktree(scratch, keep=False, repo=repo)

    assert not scratch.exists()
    assert str(scratch) not in _git(repo, "worktree", "list", "--porcelain").stdout
    # the branch must be free again — this is exactly what the ghost used to block
    again = tmp_path / "again"
    _git(repo, "worktree", "add", "-q", str(again), "public")
    assert again.joinpath("a.txt").is_file()
