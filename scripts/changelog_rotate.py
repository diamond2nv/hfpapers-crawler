#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rolling-window rotation for docs/CHANGELOG.md — the single implementation of the rule.

Same discipline as the wiki's ``scripts/rotate_log.py``:

* **one measurable criterion = bytes**, not entries (entry length drifts; a line/entry
  count is a proxy that silently stops matching the intent). Budget default 24576 B.
* keep the **newest contiguous** entries until the budget is filled, subject to a floor
  and a ceiling on how many entries may be kept;
* **refuse to rotate** when the file holds ``<= MIN_KEEP`` entries — better to exceed the
  budget than to lose the only copy of the recent history;
* **idempotent**: if already inside the budget, nothing is written;
* rotated entries move to ``docs/CHANGELOG-archive.md`` (append-only, newest first);
* the window describes itself in an HTML comment so tooling and humans can parse it:
  ``<!-- changelog-window rule="bytes<=24576" kept=20 of=44 bytes=24310 rotated=2026-09-17 -->``

Usage::

    python3 scripts/changelog_rotate.py              # rotate if needed
    python3 scripts/changelog_rotate.py --dry-run    # report only
    python3 scripts/changelog_rotate.py --check      # exit 1 if rotation is needed (gate)
    python3 scripts/changelog_rotate.py --verify-history   # no heading may vanish (gate)
    python3 scripts/changelog_rotate.py --budget N   # temporary budget override

Exit codes: 0 ok / 1 rotation needed (--check only) / 2 usage or conservation failure.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHANGELOG = REPO_ROOT / "docs" / "CHANGELOG.md"
DEFAULT_ARCHIVE = REPO_ROOT / "docs" / "CHANGELOG-archive.md"

DEFAULT_BUDGET = 24576  # bytes, matches the wiki log.md window
MIN_KEEP = 8            # never rotate below this many entries
MAX_KEEP = 40           # a window wider than this is not a window

ENTRY_RE = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\]", re.MULTILINE)
WINDOW_RE = re.compile(r"^<!-- changelog-window .*-->\n", re.MULTILINE)

ARCHIVE_HEADER = """# CHANGELOG — archive

> Entries rotated out of `docs/CHANGELOG.md` (newest first). The live file keeps a bounded window
> because a changelog is read, not diffed: the rule and the tool that implements it are
> `scripts/changelog_rotate.py`, and the window state is recorded in an HTML comment at the top of
> the live file.
>
> Nothing is lost by rotation — every past state of `docs/CHANGELOG.md` is also preserved in git
> (`git log -- docs/CHANGELOG.md`).

"""


def split(text: str) -> tuple[str, list[str]]:
    """Return (header, entries) — entries are raw blocks starting at a '## [date]' heading."""
    positions = [m.start() for m in ENTRY_RE.finditer(text)]
    if not positions:
        return text, []
    header = text[: positions[0]]
    entries = []
    for i, start in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(text)
        entries.append(text[start:end].rstrip("\n"))
    return header, entries


def entry_id(block: str) -> str:
    return block.split("\n", 1)[0].strip()


def rotate(changelog: Path, archive: Path, budget: int, dry_run: bool) -> int:
    text = changelog.read_text(encoding="utf-8")
    header, entries = split(text)
    total = len(entries)
    size = len(text.encode())

    if size <= budget:
        print(f"[ok] {changelog.name}: {total} entries / {size} B within budget ({budget} B)")
        return 0

    if total <= MIN_KEEP:
        print(f"[skip] {total} entries <= floor {MIN_KEEP} — keeping all despite {size} B")
        return 0

    # newest contiguous entries filling the budget
    kept: list[str] = []
    used = len(header.encode())
    for block in entries:
        cost = len(block.encode()) + 2  # + blank separator
        if kept and (used + cost > budget or len(kept) >= MAX_KEEP):
            break
        kept.append(block)
        used += cost
    if len(kept) < MIN_KEEP:
        kept = entries[:MIN_KEEP]
    rotated = entries[len(kept):]
    ids_kept = {entry_id(b) for b in kept}
    ids_rotated = [entry_id(b) for b in rotated]

    assert len(kept) + len(rotated) == total, "entry accounting drifted"
    assert not (ids_kept & set(ids_rotated)), "an entry is both kept and rotated"
    assert len(set(ids_rotated)) == len(ids_rotated), "duplicate headings inside the rotated set"

    new_header = WINDOW_RE.sub("", header)
    stamp = dt.date.today().isoformat()
    window = (
        f'<!-- changelog-window rule="bytes<={budget}" kept={len(kept)} of={total} '
        f'bytes={used} rotated={stamp} -->\n'
    )
    # window comment goes directly under the H1, above the prose note
    lines = new_header.split("\n")
    if lines and lines[0].startswith("# "):
        new_header = "\n".join([lines[0], "", window.rstrip("\n"), *lines[1:]])
    else:
        new_header = window + new_header
    new_changelog = new_header.rstrip("\n") + "\n\n" + "\n\n".join(kept) + "\n"

    if archive.exists():
        a_text = archive.read_text(encoding="utf-8")
        a_header, a_entries = split(a_text)
        a_ids = {entry_id(b) for b in a_entries}
        clash = [i for i in ids_rotated if i in a_ids]
        if clash:
            print(f"[error] archive already contains: {clash[:3]} — refusing (would duplicate)", file=sys.stderr)
            return 2
        new_archive = a_header.rstrip("\n") + "\n\n" + "\n\n".join(rotated + a_entries) + "\n"
    else:
        new_archive = ARCHIVE_HEADER + "\n\n".join(rotated) + "\n"
        a_entries = []

    # conservation: every original entry survives in exactly one file
    combined_ids = {entry_id(b) for b in kept} | {entry_id(b) for b in rotated}
    assert combined_ids == {entry_id(b) for b in entries}, "entry set changed during rotation"

    print(f"[rotate] keep {len(kept)} newest ({used} B <= {budget}) · move {len(rotated)} to {archive.name}")
    print(f"         changelog {size} B -> {len(new_changelog.encode())} B · "
          f"archive {len(a_entries)} -> {len(rotated + a_entries)} entries")
    if dry_run:
        print("         (dry run — nothing written)")
        return 0
    changelog.write_text(new_changelog, encoding="utf-8")
    archive.write_text(new_archive, encoding="utf-8")
    print("         written")
    return 0


def headings(text: str) -> set[str]:
    return {m.group(0).strip() for m in re.finditer(r"^## \[.*$", text, re.MULTILINE)}


def git_show(path: Path, git_dir: Path) -> str | None:
    """Return the HEAD version of ``path`` (None when git/HEAD/path is unavailable)."""
    try:
        rel = path.resolve().relative_to(git_dir)
    except ValueError:
        return None
    result = subprocess.run(
        ["git", "-C", str(git_dir), "show", f"HEAD:{rel}"],
        capture_output=True, text=True,
    )
    return result.stdout if result.returncode == 0 else None


def verify_history(changelog: Path, archive: Path) -> int:
    """Entries may move between the live file and the archive, but never disappear.

    A rotation-aware replacement for a plain "headings lost vs HEAD" check: the
    heading sets of the live file and the archive are compared *together* against
    the same two files at HEAD, so moving an entry is fine and dropping one is not.
    """
    git_dir = Path(
        subprocess.run(["git", "-C", str(changelog.parent), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True).stdout.strip() or "/nonexistent"
    )
    if not git_dir.is_dir():
        print("[skip] not a git worktree — history check unavailable")
        return 0

    now: set[str] = set()
    for f in (changelog, archive):
        if f.is_file():
            now |= headings(f.read_text(encoding="utf-8"))

    before: set[str] = set()
    seen_any = False
    for f in (changelog, archive):
        text = git_show(f, git_dir)
        if text is not None:
            seen_any = True
            before |= headings(text)
    if not seen_any:
        print("[skip] neither file exists at HEAD (first commit?)")
        return 0

    lost = sorted(before - now)
    added = len(now - before)
    if lost:
        print(f"{len(lost)} heading(s) existed at HEAD and are gone (not archived):", file=sys.stderr)
        for h in lost[:10]:
            print(f"  - {h}", file=sys.stderr)
        return 1
    print(f"[ok] no heading lost vs HEAD ({len(before)} before, {len(now)} now, +{added} new)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rotate docs/CHANGELOG.md into a bounded window.")
    p.add_argument("--changelog", default=str(DEFAULT_CHANGELOG))
    p.add_argument("--archive", default=str(DEFAULT_ARCHIVE))
    p.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--check", action="store_true",
                   help="exit 1 (no writes) when rotation is needed — used by the gate and release")
    p.add_argument("--verify-history", action="store_true",
                   help="exit 1 if an entry that exists at HEAD is missing from live+archive")
    args = p.parse_args(argv)

    changelog = Path(args.changelog)
    if not changelog.is_file():
        print(f"changelog not readable: {changelog}", file=sys.stderr)
        return 2

    if args.verify_history:
        return verify_history(changelog, Path(args.archive))

    if args.check:
        size = len(changelog.read_text(encoding="utf-8").encode())
        if size <= args.budget:
            print(f"[ok] {changelog.name} {size} B <= budget {args.budget} B")
            return 0
        print(f"{changelog.name} is {size} B, over the {args.budget} B budget.\n"
              f"Run: python3 scripts/changelog_rotate.py", file=sys.stderr)
        return 1

    return rotate(changelog, Path(args.archive), args.budget, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
