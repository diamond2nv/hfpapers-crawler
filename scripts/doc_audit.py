#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Doc-surface audit — ADVISORY, not a gate.

Checks the hand-written documentation (`docs/**`, `skills/**`, `AGENTS.md`, `README.md`)
against the repository as it actually is:

  C1  referenced repo paths exist            C4  relative markdown links resolve
  C2  documented `hfpclawer <sub>` exist     C5  capabilities in code but absent from the docs
  C3  explicit "current version" claims      C6  en/zh translation line-count drift
  C7  tracked build/runtime artifacts

Why advisory: coverage is a judgement call, and a check that cries wolf gets ignored —
the enforceable invariants (changelog coverage / window / sanitization) live in
`tests/test_gates.py` and `scripts/pre-push` instead. Run this when touching the doc
surface, and when it finds a real defect, fix the defect and (if the category is
mechanically checkable) add a gate.

Expected-missing references are whitelisted below rather than reported, so the output
stays scannable. Exit code is 0 unless `--strict` is passed.

Usage:  python3 scripts/doc_audit.py [--strict]
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
VT = tuple(int(x) for x in VERSION.split("."))

DOCS = sorted(
    [p for p in (REPO / "docs").rglob("*.md")]
    + [REPO / "AGENTS.md", REPO / "README.md"]
    + sorted((REPO / "skills").rglob("*.md"))
)
DOCS = [p for p in DOCS if p.is_file()]
# A changelog is a historical narrative: it names paths, commands and versions *as they were*
# ("the file is now called X", "0.16.0 shipped Y"). Auditing it for current-state consistency
# produces guaranteed false positives, so it is exempt from C1/C2/C3.
NARRATIVE = [p for p in DOCS if p.name.startswith("CHANGELOG")]
DOCS = [p for p in DOCS if p not in NARRATIVE]

BASENAMES = {p.name for p in REPO.rglob("*") if p.is_file() and ".git/" not in str(p)}
PATH_RE = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|md|sh|yaml|toml|jsonl|cfg|txt|in))`")
PATH_RE2 = re.compile(r"\(([A-Za-z0-9_./-]+\.(?:md|py|sh))\)")
VER_RE = re.compile(r"\bv?(\d+\.\d+\.\d+)\b")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")
EXTERNAL_PREFIXES = ("concepts/", "hedge/", "env/", ".hermes/", "wiki/", "../")
# files that are deliberately absent from the working tree (gitignored real data, third-party
# internals) — referencing them is correct documentation, not drift
EXPECTED_MISSING = (
    "scripts/researcher-audit/people.yaml",  # gitignored: real scholar ids (AGENTS.md rule 3)
    "default_en.txt",                        # inside pint's unit database
    "rotate_log.py",                         # the wiki's log rotation tool, cited by name
    "data/golden_positive.jsonl",            # ROADMAP documents it as never created
    "scripts/migrate_status.py",             # never created; _init_db idempotent ALTERs instead
    "docs/formula-cross-validation-architecture.md",  # verify-guide documents it as planned
    "docs/plans/knowledge-graph-v0.10.md",   # removed by the v0.15.0 internal-plan split
)

findings: dict[str, list[str]] = {k: [] for k in ("C1", "C2", "C3", "C4", "C5", "C6", "C7")}
notes: list[str] = []

print(f"== audited files: {len(DOCS)}  (pyproject version {VERSION})\n")

# ---------- C1 ----------
missing: dict[str, set[str]] = {}
external: set[str] = set()
resolved_by_basename: set[str] = set()
for doc in DOCS:
    text = doc.read_text(encoding="utf-8", errors="ignore")
    for m in list(PATH_RE.finditer(text)) + list(PATH_RE2.finditer(text)):
        rel = re.sub(r"^\./", "", m.group(1))
        if rel.startswith(("http", "www")):
            continue
        if rel.startswith(EXTERNAL_PREFIXES):
            external.add(rel)
            continue
        if (REPO / rel).exists() or (doc.parent / rel).exists():
            continue
        if Path(rel).name in BASENAMES and "/" not in rel:
            resolved_by_basename.add(rel)
            continue
        missing.setdefault(rel, set()).add(doc.relative_to(REPO).as_posix())
for rel in list(missing):
    if rel in EXPECTED_MISSING:
        del missing[rel]
for rel, where in sorted(missing.items()):
    findings["C1"].append(f"missing `{rel}` <- {', '.join(sorted(where)[:3])}")
notes.append(f"C1: {len(external)} external/private refs skipped (wiki/hedge/.hermes), "
             f"{len(resolved_by_basename)} bare module names resolved by basename")

# ---------- C2 (authoritative command list) ----------
cli = str(Path.home() / ".venv/bin/hfpclawer")
try:
    help_txt = subprocess.run([cli, "--help"], capture_output=True, text=True, timeout=60).stdout
    # Rich renders commands as boxed rows: "│ name  description │"
    commands = set(re.findall(r"\u2502\s+([a-z][a-z0-9-]+)\s{2,}", help_txt))
    notes.append(f"C2: CLI reports {len(commands)} commands: {', '.join(sorted(commands))}")
    MENTION = re.compile(r"`hfpclawer\s+([a-z][a-z0-9-]+)")
    # "never implemented / not a command / legacy" context is documentation, not drift
    NEGATION = re.compile(r"never implemented|not a command|legacy|未实现|不是命令|历史设计")
    bad: dict[str, set[str]] = {}
    for doc in DOCS:
        for line in doc.read_text(encoding="utf-8", errors="ignore").splitlines():
            for m in MENTION.finditer(line):
                sub = m.group(1)
                if sub not in commands and not NEGATION.search(line):
                    bad.setdefault(sub, set()).add(doc.relative_to(REPO).as_posix())
    for sub, where in sorted(bad.items()):
        findings["C2"].append(f"`hfpclawer {sub}` (backticked) not a CLI command <- {', '.join(sorted(where)[:3])}")
except Exception as exc:
    findings["C2"].append(f"could not read CLI help: {exc}")

# ---------- C3 ----------
# Only explicit "this is the current version" claims — a skill's own frontmatter
# `version: 1.0.0` is not a claim about the package version.
CLAIM_RE = re.compile(
    r"(?:current(?:ly)? version|latest version|当前版本|最新版本|version is)\s*[: ]*[`*]*v?(\d+\.\d+\.\d+)",
    re.IGNORECASE,
)
claims = {}
for doc in DOCS:
    for m in CLAIM_RE.finditer(doc.read_text(encoding="utf-8", errors="ignore")):
        claims.setdefault(m.group(1), set()).add(doc.relative_to(REPO).as_posix())
if claims:
    notes.append(f"C3: explicit version claims found: {dict((k, sorted(v)) for k, v in claims.items())}")
    for v, where in claims.items():
        if tuple(int(x) for x in v.split(".")) != VT:
            findings["C3"].append(f"stale version claim {v} (current {VERSION}) <- {', '.join(sorted(where))}")
else:
    notes.append("C3: no doc hard-codes a current version (the goal — pyproject is the single source)")

# ---------- C4 ----------
for doc in DOCS:
    for m in LINK_RE.finditer(doc.read_text(encoding="utf-8", errors="ignore")):
        target = m.group(1)
        if target.startswith(("http", "mailto")):
            continue
        if not (doc.parent / target).exists() and not (REPO / target).exists():
            findings["C4"].append(f"broken link `{target}` in {doc.relative_to(REPO)}")

# ---------- C5 ----------
CORPUS = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in DOCS)
CAPS = {
    "Europe PMC source": ["EuropePmcSource", "europepmc"],
    "bioRxiv/medRxiv source": ["BiorxivSource", "biorxiv", "medrxiv"],
    "config.local.yaml overlay": ["config.local.yaml"],
    "shared retry from anti_crawl": ["anti_crawl"],
    "changelog guard": ["changelog_guard"],
    "push gate (sanitization)": ["pre-push"],
    "public release script": ["publish-public.sh"],
    "QUIC transport / fetch CLI": ["quic"],
    "source registry": ["SOURCE_CLASSES"],
    "audit_level / verification states": ["audit_level"],
    "positive pool": ["pool"],
    "ledger": ["ledger"],
    "rank / SimClusters": ["SimClusters"],
    "Zotero sync-back": ["sync-back"],
}
for label, needles in CAPS.items():
    hits = [n for n in needles if n in CORPUS]
    if not hits:
        findings["C5"].append(f"capability `{label}` absent from all docs (needles {needles})")
    else:
        print(f"C5 ok  {label}  via {hits}")

# ---------- C6 (translation parity) ----------
# The convention (AGENTS.md) is that docs/cn/*.zh-CN.md mirror their English
# originals line for line. Drift is not a defect per se — a translated sentence can
# legitimately take more lines — but a large gap means the mirror stopped being
# maintained, and the reader cannot tell which side is current.
PARITY_TOLERANCE = 10
docs_dir = REPO / "docs"
for en_doc in sorted(docs_dir.rglob("*.md")):
    if "cn" in en_doc.relative_to(docs_dir).parts:
        continue
    zh_doc = docs_dir / "cn" / en_doc.relative_to(docs_dir).with_name(en_doc.stem + ".zh-CN.md")
    if not zh_doc.is_file():
        continue
    en_lines = len(en_doc.read_text(encoding="utf-8").splitlines())
    zh_lines = len(zh_doc.read_text(encoding="utf-8").splitlines())
    if abs(en_lines - zh_lines) > PARITY_TOLERANCE:
        findings["C6"].append(
            f"translation drift {en_lines}/{zh_lines} lines "
            f"({en_lines - zh_lines:+d}) — {en_doc.relative_to(REPO)} vs {zh_doc.relative_to(REPO)}"
        )

# ---------- C7 (tracked artifacts) ----------
# Local build/runtime output must not be tracked: it bloats clones and travels into
# the public repo. `.codegraph/` is allowed — it keeps its own .gitignore and only
# that file is tracked.
ARTIFACT_PATTERNS = (
    "*.db", "*.sqlite", "*.sqlite3", "*.pyc", "*.log", "*.orig", "*.rej",
)
ARTIFACT_DIRS = ("data/", "logs/", "dist/", "build/", "__pycache__/", ".venv/")
ARTIFACT_ALLOW = (".codegraph/",)
tracked = subprocess.run(
    ["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True
).stdout.splitlines()
for rel in tracked:
    if rel.startswith(ARTIFACT_ALLOW):
        continue
    if rel.startswith(ARTIFACT_DIRS) or any(rel.endswith(p.lstrip("*")) for p in ARTIFACT_PATTERNS):
        findings["C7"].append(f"tracked artifact `{rel}` — should be gitignored, not committed")

print()
for n in notes:
    print("note:", n)
print()
total = 0
for k in ("C1", "C2", "C3", "C4", "C5", "C6", "C7"):
    items = findings[k]
    total += len(items)
    print(f"===== {k}: {len(items)} finding(s)")
    for it in items:
        print("   -", it)
print(f"\nTOTAL findings: {total}")
print("(advisory audit — see the module docstring for why this is not a gate)")
if "--strict" in sys.argv and total:
    sys.exit(1)
