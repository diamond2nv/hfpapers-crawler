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

What it does
------------
  1. preflight — clean tree, public branch in sync with its remote, valid new version, and the
      development line's own release tag `vX.Y.Z` for that version (a public cut snapshots a
      release; it is not a snapshot of the development tip)
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
  6. gates — sanitization (sensitive values + internal layout), changelog coverage,
             and the snapshot's own test gates
  7. report — what the diff contains and the exact publish command

`--dry-run` (the default) rolls the branch back afterwards; only `--push` publishes,
and it delegates to scripts/publish-public.sh so there is a single push path.

Usage::

    python3 scripts/recut-public.py --version 0.17.4                  # dry run
    python3 scripts/recut-public.py --version 0.17.4 --push           # publish
    python3 scripts/recut-public.py --version 0.17.4 --keep-worktree  # inspect after

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

    # The public line shares the version numbers PyPI carries, so a public release must
    # obey PyPI's rule for this project: 0.x.0 with an odd x. (These are the versions
    # that exist on both surfaces; a dev-line fix release such as 0.19.1 is NAS-only
    # bookkeeping and is folded into the next aligned release.)
    major, minor, patch = (int(x) for x in args.version.split("."))
    if not (major == 0 and patch == 0 and minor % 2 == 1):
        print(
            f"{args.version} cannot be a public release: PyPI accepts only 0.x.0 with an odd x "
            "for this project (0.19.0, 0.21.0, ...). Aligning GitHub with PyPI means using the "
            "same numbers.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if not dev_release_tag(args.version):
        print(
            f"the development line has no release tag v{args.version}: a public cut snapshots a\n"
            f"release, so tag the development line first (bash scripts/release.sh {args.version}),\n"
            "then cut from that tag. (Retracted 2026-09-21: a 0.21.0 cut taken from the 0.19.7 tip.)",
            file=sys.stderr,
        )
        raise SystemExit(2)

    # Fail fast on a typo'd override: without this the raw git error surfaces only inside the
    # scratch worktree, after the worktree has already been created.
    if args.source_ref and not ref_resolves(args.source_ref):
        print(f"--source-ref {args.source_ref!r} does not resolve to a commit here", file=sys.stderr)
        raise SystemExit(2)

    latest = git("tag", "--sort=-v:refname", "--merged", args.branch, check=False).stdout.split()
    latest_public = next((t for t in latest if re.fullmatch(r"v\d+\.\d+\.\d+", t)), "")
    if latest_public:
        cur = tuple(int(x) for x in latest_public.lstrip("v").split("."))
        new = (major, minor, patch)
        if new <= cur:
            print(
                f"version {args.version} is not above the latest public tag {latest_public}",
                file=sys.stderr,
            )
            raise SystemExit(2)

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
            res = subprocess.run(
                ["/bin/sh", str(PUBLISH_SCRIPT), args.version, "--push"],
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
