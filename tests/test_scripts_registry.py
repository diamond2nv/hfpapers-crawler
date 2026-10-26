"""Gate: the `scripts/` registry cannot drift from the directory it describes.

Why this test exists
--------------------
`scripts/` holds 30 tracked files and only six of them carry a criterion; the rest stay honest
because a document says what they are. A registry nobody checks rots in one direction only —
files get added and retired while the table stays still — and then the next agent trusts it. So
the table is parsed and cross-checked here:

1. **coverage** — every tracked file under `scripts/` appears in the registry exactly once, and
   every row names a file that exists and is tracked (no orphan rows, no undocumented script);
2. **vocabulary** — `类型`/`状态` come from the fixed sets, and a `gate` row also appears in the
   §2 判据 table (a gate without an exit-code contract is not a gate);
3. **entry** — every row's 入口 cell names its own file (`bash scripts/x.sh …`), so the table
   cannot describe an entry point that does not exist;
4. **lifecycle** — a row marked `superseded` must say `SUPERSEDED` in its own file header, which
   is the convention that makes retirement legible instead of deletion;
5. **consumers** — a `gate` must be referenced at least once outside itself (by `release.sh`,
   `recut-public.py`, `pre-push`, `publish-public.sh`, the tests, or the docs).

The registry lives in `scripts/AGENTS.md` when that file exists (it is the nested agent guide),
otherwise in `scripts/README.md`. Exactly one of them is read, so a rename cannot silently
disable this gate.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"

TYPES = {"gate", "publish", "cron", "pipeline", "one-off", "template", "lib"}
STATUSES = {"active", "one-off", "superseded", "template"}

#: Files whose content counts as "someone consumes this gate".
CONSUMERS = (
    "scripts/release.sh",
    "scripts/recut-public.py",
    "scripts/publish-public.sh",
    "scripts/pre-push",
    "scripts/changelog_guard.py",
    "scripts/doc_audit.py",
    "tests",
    "AGENTS.md",
    "docs",
)


def _registry_path() -> Path:
    for name in ("AGENTS.md", "README.md"):
        candidate = SCRIPTS / name
        if candidate.is_file():
            return candidate
    pytest.skip("no scripts/ registry document (AGENTS.md or README.md)")


def _cells(line: str) -> list[str]:
    """Split a markdown table row on unescaped pipes only (entries carry `\\|`)."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def _table_after(text: str, heading: str) -> list[list[str]]:
    """Rows of the first markdown table that follows `heading` (header + separator dropped)."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip().startswith(heading))
    except StopIteration:  # pragma: no cover - the sections are part of the contract
        pytest.fail(f"registry document has no section {heading!r}")
    rows: list[list[str]] = []
    seen_table = False
    for line in lines[start + 1:]:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if not stripped.startswith("|"):
            if seen_table and rows:
                break
            continue
        seen_table = True
        cells = _cells(stripped)
        if all(set(c) <= set("-: ") for c in cells):  # separator row
            continue
        if cells and cells[0].lower() in {"文件", "脚本"}:  # header row
            continue
        rows.append(cells)
    return rows


def _registry_rows() -> list[list[str]]:
    return _table_after(_registry_path().read_text(encoding="utf-8"), "## 1.")


def _criterion_rows() -> list[list[str]]:
    return _table_after(_registry_path().read_text(encoding="utf-8"), "## 2.")


def _documented_files() -> set[str]:
    files: set[str] = set()
    for row in _registry_rows():
        assert row, "empty registry row"
        files.add(row[0].strip("`"))
    return files


def _tracked_files() -> set[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "scripts/"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return {
        p[len("scripts/"):]
        for p in out
        if "__pycache__" not in p and not p.startswith("scripts/__pycache__")
    }


def test_every_tracked_script_is_registered_exactly_once() -> None:
    rows = _registry_rows()
    names = [row[0].strip("`") for row in rows]
    assert len(names) == len(set(names)), f"a file is registered twice: {sorted(names)}"

    registry_doc = _registry_path().name
    tracked = _tracked_files() - {registry_doc}
    documented = _documented_files()

    undocumented = sorted(tracked - documented)
    phantom = sorted(documented - tracked)
    assert not undocumented, (
        f"{len(undocumented)} file(s) under scripts/ are not in the registry: {undocumented} — "
        f"register them in scripts/{registry_doc} §1 (type/entry/caller/criterion/status)"
    )
    assert not phantom, (
        f"{len(phantom)} registry row(s) name a file that is not tracked: {phantom} — "
        "either the file was renamed/removed, or the row is stale"
    )


def test_rows_use_the_documented_vocabulary() -> None:
    for row in _registry_rows():
        assert len(row) >= 6, f"registry row is missing columns: {row}"
        file, kind, entry, caller, criterion, status = row[:6]
        name = file.strip("`")
        assert kind in TYPES, f"{name}: 类型 {kind!r} not in {sorted(TYPES)}"
        assert status in STATUSES, f"{name}: 状态 {status!r} not in {sorted(STATUSES)}"
        assert caller.strip(), f"{name}: 调用者 column is empty (say `无（手工）` if nobody calls it)"
        assert criterion.strip(), f"{name}: 判据/产物 column is empty"
        assert name in entry, (
            f"{name}: 入口 cell must name the file itself so the entry point is checkable, "
            f"got {entry!r}"
        )


def test_every_gate_carries_an_exit_code_contract() -> None:
    """A gate that is not in §2 has no exit codes, i.e. nothing can depend on it."""
    gates = {row[0].strip("`") for row in _registry_rows() if row[1] == "gate"}
    assert gates, "no gate is registered — the vocabulary test would have caught a typo"
    documented = {row[0].strip("`") for row in _criterion_rows()}
    missing = sorted(gates - documented)
    assert not missing, (
        f"gate(s) registered but absent from §2 判据 (no exit-code contract): {missing}"
    )


def test_superseded_rows_say_so_in_their_own_header() -> None:
    superseded = [
        row[0].strip("`") for row in _registry_rows() if row[5] == "superseded"
    ]
    assert superseded, "the superseded convention is untested — keep one such row"
    for name in superseded:
        head = (SCRIPTS / name).read_text(encoding="utf-8").splitlines()[:12]
        assert any("SUPERSEDED" in line for line in head), (
            f"{name} is marked superseded in the registry but its header never says "
            "`SUPERSEDED by <file> (vX.Y.Z)` — retirement must be legible from the file alone"
        )


def test_every_gate_has_a_consumer_outside_itself() -> None:
    for row in _registry_rows():
        if row[1] != "gate":
            continue
        name = row[0].strip("`")
        basename = Path(name).name
        hits: list[str] = []
        for scope in CONSUMERS:
            target = REPO_ROOT / scope
            if not target.exists():
                continue
            result = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "grep", "-l", "-F", basename, "--", scope],
                capture_output=True,
                text=True,
            )
            hits.extend(
                p for p in result.stdout.split() if p != f"scripts/{name}"
            )
        assert hits, (
            f"{name} is registered as a gate but nothing consumes it (searched "
            f"{', '.join(CONSUMERS)}). Either wire it into a caller/test or reclassify it."
        )
