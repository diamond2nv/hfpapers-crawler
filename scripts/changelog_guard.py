#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Changelog coverage guard.

Single implementation of the question "is this version documented?", shared by
two callers so the rule cannot drift into two copies:

  * ``scripts/release.sh``  — refuses to tag a version with no changelog entry
  * ``tests/test_gates.py`` — TestChangelogGate (F03) drives this script's CLI

The changelog is a bounded rolling window: entries rotate into
``docs/CHANGELOG-archive.md`` (rule: ``scripts/changelog_rotate.py``). A version is
"documented" if it appears in **either** file — rotation must not make an old release
look undocumented.

An entry is a top-level changelog heading of the form::

    ## [YYYY-MM-DD] <type> | vX.Y.Z — <summary>

The version match is boundary-anchored, so an entry for ``v0.18.10`` does not
satisfy a lookup for ``v0.18.1`` — the failure mode that makes a substring
check silently useless.

Usage::

    python3 scripts/changelog_guard.py 0.18.15 [--changelog PATH] [--quiet]

Exit codes: 0 documented · 1 not documented · 2 usage or unreadable changelog.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHANGELOG = REPO_ROOT / "docs" / "CHANGELOG.md"
DEFAULT_ARCHIVE = REPO_ROOT / "docs" / "CHANGELOG-archive.md"

TOP_LEVEL_ENTRY = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\](.*)$", re.MULTILINE)


def find_entry(version: str, *paths: Path) -> tuple[str, str, Path] | None:
    """Return (date, heading, file) of the top-level entry for ``version``, or None.

    Searched across every candidate path in order (live changelog first, then the
    rotation archive) so a rotated-out release is still found.
    """
    pattern = re.compile(rf"\bv{re.escape(version)}(?![0-9])")
    for path in paths:
        if not path.is_file():
            continue
        for match in TOP_LEVEL_ENTRY.finditer(path.read_text(encoding="utf-8")):
            if pattern.search(match.group(2)):
                return match.group(1), match.group(0).strip(), path
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that a version has a top-level changelog entry."
    )
    parser.add_argument("version", help="version to look for, without the leading 'v' (e.g. 0.18.15)")
    parser.add_argument(
        "--changelog",
        default=str(DEFAULT_CHANGELOG),
        help="path to the live changelog (default: docs/CHANGELOG.md next to this script)",
    )
    parser.add_argument(
        "--archive",
        default=str(DEFAULT_ARCHIVE),
        help="path to the rotation archive, also searched (default: docs/CHANGELOG-archive.md)",
    )
    parser.add_argument("--quiet", action="store_true", help="print nothing on success")
    args = parser.parse_args(argv)

    version = args.version.strip().lstrip("vV")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        print(f"usage: version must be semver (e.g. 0.18.15), got: {args.version!r}", file=sys.stderr)
        return 2

    changelog = Path(args.changelog)
    archive = Path(args.archive)
    if not changelog.is_file():
        print(f"changelog not readable: {changelog}", file=sys.stderr)
        return 2

    found = find_entry(version, changelog, archive)
    if found is None:
        searched = ", ".join(str(p) for p in (changelog, archive) if p.is_file())
        print(
            f"v{version} has no top-level entry in: {searched or changelog}.\n"
            f"Add one before tagging, in this form:\n"
            f"  ## [YYYY-MM-DD] <feat|fix|docs|chore> | v{version} — <summary>\n"
            f"  - **A/M** `path` — what changed and why",
            file=sys.stderr,
        )
        return 1

    date, heading, where = found
    if not args.quiet:
        print(f"OK  v{version} documented — [{date}] {heading.split(']', 1)[-1].strip()}"
              f"  ({where.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
