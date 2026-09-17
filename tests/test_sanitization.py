#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sanitization-surface gate (F07).

The repository is published in two places and one of them is public, so the rules
about what may be committed are enforced by machines: ``scripts/pre-push``
(installed as the git hook) and ``scripts/publish-public.sh``. Both read their
patterns from ``scripts/sanitize-patterns.sh`` — this test reads the *same file*
and applies the same judgement to the working tree, so a pattern can never be
tightened in one place and forgotten in another.

Two classes, two severities:

* **sensitive values** — real ORCIDs, LAN IPs, machine codenames, personal
  emails, tokens. Files that document or implement the rules are exempt
  (``SENSITIVE_ALLOW``), because they must contain the patterns to do their job.
* **internal layout and project names** — local directory layout, private sibling
  repository names, internal wiki/mirror hosts. Only the gate scripts themselves
  are exempt: the whole point is that no other file may carry them. This class
  slipped past the older patterns twice (``/home/[a-z]+`` cannot match ``~/``),
  which is why it is gated rather than trusting review.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

pytestmark_gate_f = pytest.mark.gate_f

PATTERNS_FILE = Path(__file__).resolve().parent.parent / "scripts" / "sanitize-patterns.sh"


def _shell_vars() -> dict:
    """Extract NAME=value assignments from the shared pattern file."""
    text = PATTERNS_FILE.read_text(encoding="utf-8")
    found = {}
    for name, raw in re.findall(r"^([A-Z_]+)='(.*)'$", text, re.MULTILINE):
        found[name] = raw
    return found


def _tracked_files() -> list[str]:
    # -C so the query works regardless of the working directory (the test suite
    # chdirs into a temp dir for isolation).
    repo = PATTERNS_FILE.parent.parent
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


class TestSanitizationSurface:
    """F07: the shared sanitization patterns hold on the working tree."""

    def test_pattern_file_exists_and_defines_both_classes(self):
        assert PATTERNS_FILE.is_file(), f"missing {PATTERNS_FILE}"
        variables = _shell_vars()
        for name in (
            "SENSITIVE_PAT",
            "SENSITIVE_ALLOW",
            "OK_PLACEHOLDER",
            "LAYOUT_PAT",
            "LAYOUT_ALLOW",
        ):
            assert name in variables, f"{name} not defined in {PATTERNS_FILE.name}"

    def test_sensitive_values_match_the_agreed_placeholders_only(self):
        variables = _shell_vars()
        pattern = re.compile(variables["SENSITIVE_PAT"])
        allow = re.compile(variables["SENSITIVE_ALLOW"])
        placeholder = re.compile(variables["OK_PLACEHOLDER"])

        offenders = []
        for rel in _tracked_files():
            if allow.search(rel):
                continue
            try:
                text = (PATTERNS_FILE.parent.parent / rel).read_text(
                    encoding="utf-8", errors="ignore"
                )
            except (OSError, IsADirectoryError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if placeholder.search(line):
                    continue
                match = pattern.search(line)
                if match:
                    offenders.append(f"{rel}:{lineno}: {match.group(0)[:24]}")
        assert not offenders, (
            "sensitive values found in tracked files (see AGENTS.md rule 6 for the "
            "placeholders):\n" + "\n".join(offenders)
        )

    def test_internal_layout_and_project_names_never_appear(self):
        """The class the older patterns could not see — enforced with no back door."""
        variables = _shell_vars()
        pattern = re.compile(variables["LAYOUT_PAT"])
        allow = re.compile(variables["LAYOUT_ALLOW"])

        offenders = []
        for rel in _tracked_files():
            if allow.search(rel):
                continue
            try:
                text = (PATTERNS_FILE.parent.parent / rel).read_text(
                    encoding="utf-8", errors="ignore"
                )
            except (OSError, IsADirectoryError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                match = pattern.search(line)
                if match:
                    offenders.append(f"{rel}:{lineno}: {match.group(0)}")
        assert not offenders, (
            "internal layout or private project names in tracked files — declare "
            "peers through the environment (HFPCLAWER_PEER_REPOS / "
            "HFPCLAWER_REPO_MAP) and keep real values in gitignored files:\n"
            + "\n".join(offenders)
        )

    def test_packages_carry_no_layout_markers(self):
        """The shipped packages, checked with the same patterns as the hooks.

        Derived from the shared pattern file rather than a bespoke string, so the
        gate and this test cannot drift apart.
        """
        pattern = re.compile(_shell_vars()["LAYOUT_PAT"])
        root = PATTERNS_FILE.parent.parent
        offenders = []
        for pkg in ("hfpapers", "hfpclawer"):
            for path in sorted((root / pkg).rglob("*.py")):
                for lineno, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1
                ):
                    match = pattern.search(line)
                    if match:
                        offenders.append(
                            f"{path.relative_to(root)}:{lineno}: {match.group(0)}"
                        )
        assert not offenders, (
            "peer repositories must come from the environment, not a fixed home "
            "directory layout:\n" + "\n".join(offenders)
        )
