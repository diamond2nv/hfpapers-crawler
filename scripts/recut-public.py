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
  1. preflight — clean tree, public branch in sync with its remote, valid new version
  2. worktree — checks `public` out into a scratch directory (the dev line is untouched)
  3. sync — `git checkout <dev> -- .` to lay the development line's content on top
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
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PUBLISH_SCRIPT = REPO / "scripts" / "publish-public.sh"
GUARD = REPO / "scripts" / "changelog_guard.py"
SNAPSHOT_TESTS = ("tests/test_gates.py", "tests/test_paths.py", "tests/test_sanitization.py")


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

    for ref in (args.branch, args.source):
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

    latest = git("tag", "--sort=-v:refname", "--merged", args.branch, check=False).stdout.split()
    latest_public = next((t for t in latest if re.fullmatch(r"v0\.17\.\d+", t)), "")
    if latest_public:
        cur = tuple(int(x) for x in latest_public.lstrip("v").split("."))
        new = tuple(int(x) for x in args.version.split("."))
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recut the public line from the development line.")
    parser.add_argument("--version", required=True, help="public version to cut (semver, e.g. 0.17.4)")
    parser.add_argument("--source", default="main", help="development branch to cut from (default: main)")
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
    args = parser.parse_args(argv)

    step("preflight")
    public_sha, author = preflight(args)
    print(f"public head : {public_sha[:8]}")
    print(f"author      : {author}")
    print(f"source      : {args.source}")
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

        step(f"sync content from {args.source}")
        git("checkout", args.source, "--", ".", cwd=worktree)
        changed = git("status", "--porcelain", cwd=worktree).stdout.count("\n")
        print(f"{changed} path(s) differ from the current public tree")

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
            f"Sanitized cut of the development line ({args.source}) for the public repo. "
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
            run(["/bin/sh", str(PUBLISH_SCRIPT), args.version, "--push"], cwd=worktree)
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
