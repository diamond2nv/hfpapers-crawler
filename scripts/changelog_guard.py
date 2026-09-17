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

An entry is normally a top-level changelog heading of the form::

    ## [YYYY-MM-DD] <type> | vX.Y.Z — <summary>

The public line has its own version sequence and is documented in a dedicated
section, whose entries are one level deeper::

    ## Public line — sanitized recuts

    ### [YYYY-MM-DD] <type> | v0.17.3 — <summary>

Both are accepted — a `###` entry counts only inside a section whose title marks
it as the public line, so subsections of a development entry can never be mistaken
for a release. (Before this, the only way to make a public release pass was to
smuggle its entry into the top level, which is exactly the kind of workaround the
gate should not require.)

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

ENTRY = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\](.*)$")
PUBLIC_LINE_SECTION = re.compile(r"public line", re.IGNORECASE)


def iter_entries(text: str):
    """Yield ``(date, heading, is_public_line_entry)`` for every changelog entry.

    Top-level ``##`` entries count anywhere. Nested ``###`` entries count only
    inside a section that marks itself as the public line.
    """
    section_is_public = False
    for line in text.splitlines():
        if line.startswith("## "):
            title = line[3:].strip()
            section_is_public = bool(PUBLIC_LINE_SECTION.search(title))
            match = ENTRY.match(title)
            if match:
                yield match.group(1), title, False
        elif line.startswith("### "):
            if not section_is_public:
                continue
            match = ENTRY.match(line[4:].strip())
            if match:
                yield match.group(1), line[4:].strip(), True


def find_entry(version: str, *paths: Path) -> tuple[str, str, bool, Path] | None:
    """Return (date, heading, is_public_line, file) for ``version``, or None.

    Searched across every candidate path in order (live changelog first, then the
    rotation archive) so a rotated-out release is still found.
    """
    pattern = re.compile(rf"\bv{re.escape(version)}(?![0-9])")
    for path in paths:
        if not path.is_file():
            continue
        for date, heading, is_public in iter_entries(path.read_text(encoding="utf-8")):
            if pattern.search(heading):
                return date, heading, is_public, path
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
            f"v{version} has no entry in: {searched or changelog}.\n"
            f"Add one before tagging, in this form:\n"
            f"  ## [YYYY-MM-DD] <feat|fix|docs|chore> | v{version} — <summary>\n"
            f"  - **A/M** `path` — what changed and why\n"
            f"For a public-line release, a `###` entry under the \"Public line\" section counts too.",
            file=sys.stderr,
        )
        return 1

    date, heading, is_public, where = found
    if not args.quiet:
        kind = "public-line" if is_public else "top-level"
        print(f"OK  v{version} documented ({kind}) — [{date}] {heading.split(']', 1)[-1].strip()}"
              f"  ({where.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
