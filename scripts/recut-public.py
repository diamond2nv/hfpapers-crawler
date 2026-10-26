#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recut the public line from the development line — the six steps, mechanised.

Why this exists
---------------
The public line is not a push mirror: it is a rewritten history with its own version
sequence, published as *one sanitized commit per release*. Doing that by hand went
wrong repeatedly (2026-09-17): the version silently reverted to the development line's,
the changelog entry the coverage gate demands was missing, the sanitization gate
rejected documentation that quoted the very literals it bans, and the push was blocked
by the hook. Each of those is a check this script now runs for the operator.

Two modes (2026-10-26)
----------------------
``--mode release`` (default) — the published release. Version must be ``0.x.0`` with an **odd**
``x`` (PyPI carries the same number), a development tag ``vX.Y.Z`` must exist, the tree is that
tag, and the push creates tag + GitHub release + (separately) the PyPI upload.

``--mode sync`` — **continuous public commits, not a release**. Any development version may be
synced (even ``x``), the tree is that development tag, and **no tag, no GitHub release and no
PyPI upload happen**: the push is a plain commit on ``master`` whose message carries
``Public-Sync: vX.Y.Z`` / ``Dev-Tag: vX.Y.Z`` trailers so the published high-water mark stays
machine-readable. This is how the public repo tracks the development line between releases
without ever publishing the private history.

What it does
------------
  1. preflight — clean tree, public branch in sync with its remote, valid new version, the
      development line's own release tag `vX.Y.Z` for that version (a public cut snapshots a
      release; it is not a snapshot of the development tip), and a version above the public
      line's high-water mark. ``judge_request`` holds that whole matrix in one place.
  2. worktree — checks `public` out into a scratch directory (the dev line is untouched)
  3. sync — `git checkout vX.Y.Z -- .` to lay that *release tag's* content on top; `--source <branch>`
      and `--source-ref <ref>` are explicit overrides that forfeit the release-snapshot invariant
      (the script says so on stderr and prints both commits)
  3b. public-only paths — refuse the cut if the public tree carries tracked files the
      development line does not have: the sync copies the *content* of shared paths and
      never deletes, so dead files accumulate there (2026-09-21: three stale requirement
      lists kept 55 Dependabot advisories open across several recuts). Allowlist a
      legitimately public-only file with `--allow-public-only <glob>`.
  4. version — set the public version *after* the sync (the sync overwrites it)
  5. commit — one commit, signed with the public identity
  6. gates — sanitization (sensitive values + internal layout), changelog coverage
             (release mode only), and the snapshot's own test gates
  7. report — what the diff contains and the exact publish command

`--dry-run` (the default) rolls the branch back afterwards; only `--push` publishes,
and it delegates to scripts/publish-public.sh so there is a single push path
(`sync` mode passes `--no-tag`, because a sync must not create a release tag).

Usage::

    python3 scripts/recut-public.py --version 0.21.0                  # dry run (release)
    python3 scripts/recut-public.py --version 0.21.0 --push           # publish a release
    python3 scripts/recut-public.py --mode sync --version 0.20.3      # dry run (continuous)
    python3 scripts/recut-public.py --mode sync --version 0.20.3 --push

Exit codes: 0 ok · 1 a gate refused · 2 usage/precondition failure.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePath

REPO = Path(__file__).resolve().parents[1]
PUBLISH_SCRIPT = REPO / "scripts" / "publish-public.sh"
GUARD = REPO / "scripts" / "changelog_guard.py"
SNAPSHOT_TESTS = (
    "tests/test_gates.py",
    "tests/test_paths.py",
    "tests/test_sanitization.py",
    "tests/test_recut_public.py",  # the public-only-paths gate's own regression test
)


def run(cmd: list[str], cwd: Path = REPO, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"✗ {' '.join(cmd)}", file=sys.stderr)
        print((result.stdout + result.stderr).strip()[-2000:], file=sys.stderr)
        raise SystemExit(2)
    return result


def git(*args: str, cwd: Path = REPO, check: bool = True) -> subprocess.CompletedProcess:
    return run(["git", *args], cwd=cwd, check=check)


def step(text: str) -> None:
    print(f"\n── {text}")


RELEASE_VERSION_RE = re.compile(r"^0\.(\d+)\.0$")


def is_public_release_version(version: str) -> bool:
    """Whether ``version`` may be a *published* release: ``0.x.0`` with an odd ``x``.

    PyPI carries the same number as the GitHub tag, and this project's PyPI accepts only that
    shape (0.19.0, 0.21.0, …). A development fix release such as ``0.20.3`` is NAS-only
    bookkeeping; it may be *synced* to the public repo but never *released* there.
    """
    match = RELEASE_VERSION_RE.fullmatch(version)
    return bool(match) and int(match.group(1)) % 2 == 1


def version_tuple(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def public_high_water(branch: str = "public", repo: Path = REPO) -> tuple[str, str]:
    """The highest version the public line has already published *or* synced.

    Two machine-readable sources, because the two modes write different marks: release tags
    (``public-vX.Y.Z`` locally, ``vX.Y.Z`` on the remote) and the ``Public-Sync:`` trailer that
    sync commits carry. Returns ``(version, where)``; ``("", "")`` when the line has neither.

    Why it exists (2026-10-26): the public tree once showed ``version = 0.19.0`` while its content
    was development ``0.19.7`` — one number describing two trees. A monotonic high-water mark is
    what makes "the default branch version is the tree's version" enforceable.
    """
    best: tuple[int, int, int] | None = None
    where = ""
    for tag in git("tag", "--merged", branch, cwd=repo, check=False).stdout.split():
        name = tag[len("public-") :] if tag.startswith("public-") else tag
        if re.fullmatch(r"v\d+\.\d+\.\d+", name):
            candidate = version_tuple(name[1:])
            if best is None or candidate > best:
                best, where = candidate, f"tag {tag}"
    trailers = git(
        "log", branch, "--format=%(trailers:key=Public-Sync,valueonly)", cwd=repo, check=False
    ).stdout
    for line in trailers.splitlines():
        match = re.fullmatch(r"\s*v?(\d+\.\d+\.\d+)\s*", line)
        if match:
            candidate = version_tuple(match.group(1))
            if best is None or candidate > best:
                best, where = candidate, "trailer Public-Sync"
    if best is None:
        return "", ""
    return ".".join(str(part) for part in best), where


def judge_request(
    mode: str,
    version: str,
    high_water: str,
    dev_tag: str,
    newest_dev: str = "",
    allow_stale: bool = False,
) -> str:
    """The whole accept/refuse matrix for a public push, in one testable place.

    Returns ``""`` when the request is allowed, else the refusal message. Order matters: the
    PyPI version rule is a *release* rule, a development tag is required by *both* modes (the
    tree must be traceable to something the development line released), and monotonicity is what
    stops a sync from walking the public version backwards.

    ``newest_dev`` guards the mirror-image mistake (2026-10-26): syncing an *older* development
    release under a *higher* public version would put older content behind a newer number — the
    same "one number, two trees" trap the high-water mark exists to prevent, from the other side.
    """
    if mode == "release" and not is_public_release_version(version):
        return (
            f"{version} cannot be a public release: PyPI accepts only 0.x.0 with an odd x "
            "for this project (0.19.0, 0.21.0, ...). Aligning GitHub with PyPI means using the "
            "same numbers. To publish continuous commits without a release, use --mode sync."
        )
    if not dev_tag:
        return (
            f"the development line has no release tag v{version}: a public push snapshots a\n"
            f"release, so tag the development line first (bash scripts/release.sh {version}),\n"
            "and push from that tag. (Retracted 2026-09-21: a 0.21.0 cut taken from the 0.19.7 tip.)"
        )
    if high_water and version_tuple(version) <= version_tuple(high_water):
        return (
            f"version {version} is not above the public line's high-water mark {high_water}: "
            "the default branch must describe one tree with one number, so a public push may "
            "only move forward."
        )
    if mode == "sync" and not allow_stale and newest_dev:
        if version_tuple(version) < version_tuple(newest_dev.lstrip("v")):
            return (
                f"refusing to sync v{version}: the development line has already released "
                f"{newest_dev}. Syncing an older tree under a higher public version is the same "
                "'one number, two trees' trap, mirrored. Sync the newest development release, or "
                "pass --allow-stale-source if the older tree is genuinely what should be public."
            )
    return ""


def newest_dev_tag(repo: Path = REPO) -> str:
    """Newest development release tag (``vX.Y.Z``) reachable from the development line.

    Used by sync mode: the public tree should track the *newest* development release, not an
    older one under a higher number. Returns ``""`` when no development tag is visible.
    """
    for ref in ("forgejo/main", "origin/main", "main"):
        if git("rev-parse", "--verify", "--quiet", ref, cwd=repo, check=False).returncode != 0:
            continue
        for tag in git("tag", "--sort=-v:refname", "--merged", ref, cwd=repo, check=False).stdout.split():
            if re.fullmatch(r"v0\.\d+\.\d+", tag):
                return tag
        return ""
    return ""


def preflight(args) -> tuple[str, str]:
    """Validate the request; return (public_sha, author) of the current public head."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        print(f"version must be semver (e.g. 0.17.4), got {args.version!r}", file=sys.stderr)
        raise SystemExit(2)

    if git("status", "--porcelain").stdout.strip():
        print("working tree is not clean — commit or stash first", file=sys.stderr)
        raise SystemExit(2)

    # `--source` is an explicit override and therefore optional; the default cut takes its tree
    # from the development release tag (resolve_source_ref), so an empty value is not a branch.
    for ref in [args.branch] + ([args.source] if args.source else []):
        exists = git("rev-parse", "--verify", f"refs/heads/{ref}", check=False)
        if exists.returncode != 0:
            print(f"no such local branch: {ref}", file=sys.stderr)
            raise SystemExit(2)

    remote_ref = f"{args.remote}/{args.public_remote_branch}"
    if git("rev-parse", "--verify", remote_ref, check=False).returncode != 0:
        print(f"{remote_ref} is not cached locally — fetching {args.remote}")
        git("fetch", args.remote, check=False)
    if git("rev-parse", "--verify", remote_ref, check=False).returncode != 0:
        print(
            f"cannot resolve {remote_ref} even after fetching {args.remote} — "
            "check the remote name and that credentials work.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    public_sha = git("rev-parse", args.branch).stdout.strip()
    remote_sha = git("rev-parse", remote_ref).stdout.strip()
    if public_sha != remote_sha and not args.allow_diverged:
        print(
            f"{args.branch} ({public_sha[:8]}) is not in sync with {remote_ref} "
            f"({remote_sha[:8]}).\nA recut replaces the tip of the public branch, so it "
            "must start from the published state — fetch, or pass --allow-diverged "
            "if you know what you are doing.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    # One matrix, one place (judge_request): the PyPI version rule is a *release* rule; a
    # development tag is required by both modes; monotonicity is what keeps the default branch
    # describing one tree with one number.
    high_water, high_where = public_high_water(args.branch)
    newest_dev = newest_dev_tag() if args.mode == "sync" else ""
    refusal = judge_request(
        args.mode,
        args.version,
        high_water,
        dev_release_tag(args.version),
        newest_dev=newest_dev,
        allow_stale=args.allow_stale_source,
    )
    if refusal:
        print(refusal, file=sys.stderr)
        raise SystemExit(2)

    # Fail fast on a typo'd override: without this the raw git error surfaces only inside the
    # scratch worktree, after the worktree has already been created.
    if args.source_ref and not ref_resolves(args.source_ref):
        print(f"--source-ref {args.source_ref!r} does not resolve to a commit here", file=sys.stderr)
        raise SystemExit(2)

    if high_water:
        print(f"public high-water: v{high_water} ({high_where})")

    author = args.author or git(
        "log", "-1", "--format=%an <%ae>", args.branch
    ).stdout.strip()
    return public_sha, author



def dev_release_tag(version: str, repo: Path = REPO) -> str:
    """The development line's own release tag for ``version`` ("" when it does not exist).

    The public cut is a *sanitized snapshot of a release*, not of whatever the development tip
    happens to be: the v0.19.0 cut was taken from the dev tag `v0.19.0` itself. Cutting from the
    tip of a version the development line has not reached stamps unreleased work with a number
    nobody can trace -- measured 2026-09-21, when a `0.21.0` cut was taken from the `0.19.7` tip
    and had to be retracted.
    """
    name = f"v{version}"
    ok = git("rev-parse", "--verify", "--quiet", f"refs/tags/{name}", cwd=repo, check=False).returncode == 0
    return name if ok else ""


def ref_resolves(ref: str, repo: Path = REPO) -> bool:
    """Whether ``ref`` names a commit in this checkout (any branch, tag or sha)."""
    return git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", cwd=repo, check=False).returncode == 0


def commit_of(ref: str, repo: Path = REPO) -> str:
    """The commit ``ref`` points at ("" when it does not resolve)."""
    result = git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", cwd=repo, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def resolve_source_ref(version: str, source: str = "", source_ref: str = "") -> tuple[str, str]:
    """Which tree the cut lays on the public branch, and why — ``(ref, mode)``.

    ``mode`` is ``"tag"`` for the invariant (the development line's own release tag ``vVERSION``),
    ``"explicit-ref"`` for a caller-supplied ``--source-ref``, and ``"branch"`` for a caller-supplied
    ``--source`` branch tip. Only the first is traceable to a release; the other two exist as
    escape hatches, and the caller warns about them.

    Regression guard (2026-09-23): ``--source`` used to default to ``"main"``, which made the
    *default* cut take the branch tip while the gate added 2026-09-21 (a dev tag must exist) only
    checked that the tag was there — the tree still came from the tip. That is the same shape of
    error that forced the 0.21.0 retraction, so the default is now the tag itself.
    """
    if source_ref:
        return source_ref, "explicit-ref"
    if source:
        return source, "branch"
    return f"v{version}", "tag"  # preflight has already proven this tag exists


def source_is_release(version: str, ref: str, repo: Path = REPO) -> bool:
    """Whether ``ref`` resolves to the very commit the development release tag ``vVERSION`` does."""
    tag = dev_release_tag(version, repo=repo)
    if not tag:
        return False
    target = commit_of(ref, repo=repo)
    return bool(target) and target == commit_of(tag, repo=repo)


def public_only_paths(
    worktree: Path, source_ref: str, allow: list[str], repo: Path = REPO
) -> list[str]:
    """Tracked paths in the public worktree that the source tree does not have.

    ``git checkout <source> -- .`` copies the content of paths present in both trees; it never
    removes a file that only the public line carries.  Without this check those files survive
    every recut silently -- which is how a 188-line v0.1.3 requirement freeze kept 55 Dependabot
    advisories open.  The repo's rule is gates rather than discipline, so the cut refuses instead.
    """
    public = {p for p in git("ls-files", cwd=worktree).stdout.split("\n") if p}
    source = {
        p for p in git("ls-tree", "-r", "--name-only", source_ref, cwd=repo).stdout.split("\n") if p
    }
    stale = sorted(public - source)
    if allow:
        stale = [p for p in stale if not any(PurePath(p).match(glob) for glob in allow)]
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recut the public line from the development line.")
    parser.add_argument("--version", required=True, help="public version to cut (semver, e.g. 0.17.4)")
    parser.add_argument(
        "--mode",
        choices=("release", "sync"),
        default="release",
        help=(
            "release (default): a published release — 0.x.0 with an odd x, creating tag + GitHub "
            "release + PyPI alignment. sync: continuous public commits — any development version, "
            "no tag, no release, no upload (the public repo tracks the dev line between releases)"
        ),
    )
    parser.add_argument(
        "--source",
        default="",
        help=(
            "development branch to cut from — an explicit override. By default the tree comes from "
            "the development release tag vVERSION, because a public cut snapshots a release; "
            "passing a branch forfeits that invariant (the script warns)"
        ),
    )
    parser.add_argument(
        "--source-ref",
        default="",
        help=(
            "exact ref to take the tree from (e.g. 'v0.19.0^{}'); "
            "defaults to the development release tag vVERSION"
        ),
    )
    parser.add_argument("--branch", default="public", help="local public branch (default: public)")
    parser.add_argument("--remote", default="github", help="public remote (default: github)")
    parser.add_argument(
        "--public-remote-branch", default="master", help="remote branch the public line tracks"
    )
    parser.add_argument("--author", default="", help="public identity to sign the commit with")
    parser.add_argument("--message", default="", help="commit message (default: a generated one)")
    parser.add_argument("--push", action="store_true", help="publish (otherwise dry run)")
    parser.add_argument("--keep-worktree", action="store_true", help="do not remove the scratch worktree")
    parser.add_argument("--worktree", default="", help="scratch worktree path (default: a temp dir)")
    parser.add_argument("--allow-diverged", action="store_true", help="skip the in-sync precondition")
    parser.add_argument(
        "--allow-stale-source",
        action="store_true",
        help=(
            "sync an older development release than the newest one (normally refused: older "
            "content under a higher public version is the 'one number, two trees' trap)"
        ),
    )
    parser.add_argument(
        "--allow-public-only",
        action="append",
        default=[],
        metavar="GLOB",
        help="tracked path that may exist only on the public line (repeatable, e.g. '.github/**')",
    )
    args = parser.parse_args(argv)

    step("preflight")
    public_sha, author = preflight(args)
    print(f"public head : {public_sha[:8]}")
    print(f"author      : {author}")
    source_ref, source_mode = resolve_source_ref(args.version, args.source, args.source_ref)
    print(f"source      : {source_ref}  [{source_mode}]")
    print(f"version     : {args.version}{'  (dry run)' if not args.push else '  (will publish)'}")
    print(f"mode        : {args.mode} — {'published release' if args.mode == 'release' else 'continuous sync (no tag / no release / no upload)'}")

    worktree = Path(args.worktree) if args.worktree else Path(tempfile.mkdtemp(prefix="recut-public-"))
    keep = args.keep_worktree or args.push

    cleaned = False

    def cleanup() -> None:
        nonlocal cleaned
        if cleaned:
            return
        cleaned = True
        if keep:
            print(f"worktree kept: {worktree}")
            return
        git("worktree", "remove", "--force", str(worktree), check=False)
        git("branch", "-f", args.branch, public_sha, check=False)  # roll back the dry run
        print(f"rollback: {args.branch} back to {public_sha[:8]} (dry run)")

    try:
        step("worktree")
        git("worktree", "add", "--detach", str(worktree), args.branch)
        print(f"checked out {args.branch} at {worktree}")

        step(f"sync content from {source_ref}  [{source_mode}]")
        if source_mode == "tag":
            print(f"the cut snapshots the development release tag {source_ref} (the invariant)")
        elif not source_is_release(args.version, source_ref):
            tag = dev_release_tag(args.version) or f"v{args.version}"
            print(
                f"⚠️  {source_ref} override: the public line will NOT be a snapshot of {tag}\n"
                f"    {source_ref} = {commit_of(source_ref)[:8]}  vs  {tag} = {commit_of(tag)[:8]}",
                file=sys.stderr,
            )
        git("checkout", source_ref, "--", ".", cwd=worktree)
        changed = git("status", "--porcelain", cwd=worktree).stdout.count("\n")
        print(f"{changed} path(s) differ from the current public tree")

        step("gate — public-only paths")
        stale = public_only_paths(worktree, source_ref, args.allow_public_only)
        if stale:
            print(f"✗ {len(stale)} tracked path(s) exist only on the public line:", file=sys.stderr)
            for one in stale[:20]:
                print(f"    {one}", file=sys.stderr)
            print(
                "  the sync copies content, it does not mirror deletions -- delete these on the public\n"
                "  branch (git rm + commit + push) before cutting, or allowlist them with\n"
                "  --allow-public-only <glob> if they are legitimate.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print(f"✅ no public-only tracked path ({len(args.allow_public_only)} allowlist rule(s))")

        step(f"set version {args.version}")
        pyproject = worktree / "pyproject.toml"
        text = pyproject.read_text(encoding="utf-8")
        new_text, n = re.subn(r'^version = "[^"]+"', f'version = "{args.version}"', text, count=1, flags=re.M)
        if n != 1:
            print("could not find the version line in pyproject.toml", file=sys.stderr)
            raise SystemExit(2)
        pyproject.write_text(new_text, encoding="utf-8")
        print("pyproject.toml updated (the sync had reset it to the development version)")

        step("commit")
        git("add", "-A", cwd=worktree)
        if args.mode == "sync":
            trailers = f"Public-Sync: v{args.version}"
            if source_mode == "tag":
                trailers += f"\nDev-Tag: v{args.version}"
            message = args.message or (
                f"sync(public): v{args.version} — not a release\n\n"
                f"Sanitized snapshot of the development line ({source_ref}). Continuous public\n"
                "commit: no tag, no GitHub release, no PyPI upload. The published release marker\n"
                "stays the newest release tag; this commit only brings the public tree level with\n"
                "the development line.\n\n"
                f"{trailers}"
            )
        else:
            message = args.message or (
                f"v{args.version}: public snapshot\n\n"
                f"Sanitized cut of the development line ({source_ref}) for the public repo. "
                "One commit per public release; see the changelog's public-line section."
            )
        env_cmd = [
            "git",
            "-c",
            f"user.name={author.rsplit(' <', 1)[0]}",
            "-c",
            f"user.email={author.rsplit('<', 1)[-1].rstrip('>')}",
            "commit",
            "--author",
            author,
            "-m",
            message,
        ]
        run(env_cmd, cwd=worktree)
        head = git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
        git("update-ref", f"refs/heads/{args.branch}", head)  # move the branch onto the new commit
        print(f"commit {head[:8]} by {author}")

        if args.mode == "release":
            step("gate — changelog coverage")
            guard = run(
                [sys.executable, str(GUARD), args.version, "--changelog", str(worktree / "docs/CHANGELOG.md"),
                 "--archive", str(worktree / "docs/CHANGELOG-archive.md")],
                check=False,
            )
            if guard.returncode != 0:
                print("✗ the public version has no changelog entry — add one to the "
                      "public-line section (or as a top-level entry) and re-run.", file=sys.stderr)
                print(guard.stdout + guard.stderr, file=sys.stderr)
                return 1
            print(guard.stdout.strip())
        else:
            # A sync is not a release: it carries no new public version, so demanding a changelog
            # entry for it would push operators to invent release notes for a non-release.
            step("gate — changelog coverage (skipped in sync mode)")
            print("sync mode: no public release entry required (the dev line's own entry documents it)")

        step("gate — sanitization (sensitive values + internal layout)")
        sanitize = run(["/bin/sh", str(PUBLISH_SCRIPT), "--check"], cwd=worktree, check=False)
        print((sanitize.stdout + sanitize.stderr).strip())
        if sanitize.returncode != 0:
            print("✗ the snapshot would publish internal content — neutralise it and re-run.",
                  file=sys.stderr)
            return 1

        step("gate — snapshot test suite")
        tests = subprocess.run(
            [sys.executable, "-m", "pytest", *SNAPSHOT_TESTS, "-q", "--tb=line"],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(worktree)},
        )
        print(tests.stdout.strip().splitlines()[-1] if tests.stdout.strip() else "(no output)")
        if tests.returncode != 0:
            print("✗ the snapshot's own gates fail (see above) — fix before publishing.",
                  file=sys.stderr)
            print(tests.stdout[-2000:], file=sys.stderr)
            return 1

        step("summary")
        stat = git("diff", "--stat", f"{public_sha}..HEAD", cwd=worktree).stdout.strip()
        print(stat.splitlines()[-1] if stat else "(no changes)")

        if args.push:
            # publish-public.sh operates on the branch, not on a detached HEAD — without this
            # the publish step refuses and, if its output is swallowed, the release looks done
            # while nothing was pushed (that is exactly what happened on 2026-09-17).
            git("checkout", args.branch, cwd=worktree)
            publish_cmd = ["/bin/sh", str(PUBLISH_SCRIPT), args.version, "--push"]
            if args.mode == "sync":
                # A sync must not create a release tag: that is what keeps GitHub's tag list and
                # PyPI in lockstep with the released versions only.
                publish_cmd.append("--no-tag")
            res = subprocess.run(
                publish_cmd,
                cwd=worktree,
                capture_output=True,
                text=True,
            )
            print(res.stdout.strip() or "(no output)")
            if res.returncode != 0:
                print(res.stderr.strip(), file=sys.stderr)
                print("✗ the publish step failed — nothing was verified.", file=sys.stderr)
                return 1
            verify = git("ls-remote", args.remote, f"refs/heads/{args.public_remote_branch}").stdout.strip()
            local = git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
            print(f"\nremote {args.public_remote_branch}: {verify.split()[0][:8]}")
            print(f"local  {args.branch}: {local[:8]}")
            print("verified" if verify.startswith(local) else "✗ MISMATCH — inspect before trusting")
            return 0

        print("\ndry run complete — nothing was published. Rollback in progress.")
        return 0
    finally:
        if not args.push:
            cleanup()
        elif not args.keep_worktree:
            shutil.rmtree(worktree, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
