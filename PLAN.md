# hfpclawer — Plan (light)

**Scope.** This file is a one-screen summary, not the plan of record. The detailed plan is
[`docs/ROADMAP.md`](docs/ROADMAP.md); the shipped record is [`docs/CHANGELOG.md`](docs/CHANGELOG.md);
the rules an agent must follow are in [`AGENTS.md`](AGENTS.md). The v0.6.x-era plan that used to fill
this file is preserved in git (`git log -- PLAN.md`).

## What the project does

Local-first paper intelligence for agents:

1. **Find** — search several document sources through one registry, keyword- and relevance-filtered.
2. **Fetch** — download PDF/TeX through a transport ladder that survives unreliable networks, with
   resumable transfers and sha256 audit records.
3. **Verify** — record what is actually known about each paper; contradictions become `suspect`
   rather than silent corruption. Symbolic checks only, no LLM verdicts.
4. **Store** — SQLite (`data/papers.db`) with stable Snowflake ids, Crossref/arXiv identifiers, and
   an append-only acquisition audit.
5. **Serve** — CLI (`hfpclawer …`) and MCP server, so an agent can drive all of it without a UI.

## How to work in it (agent-first)

- **CLI first**: every capability worth having is a subcommand with a documented flag set — if it can
  only be done from Python internals, it is not finished.
- **Deterministic by default**: routine monitoring must cost 0 LLM calls (`check-new`), and any
  judgement call is opt-in.
- **Nothing personal in tracked files**: real names, ORCIDs, query lists and paths go in the
  gitignored overlay (`config.local.yaml`, `~/.hfpclawer/profile.yaml`).
- **Gates over discipline**: a rule that matters is a check that refuses, not a sentence in a doc —
  sanitization and changelog gates live in `scripts/pre-push` and `scripts/release.sh`; the gate
  tests live in `tests/test_gates.py`.
- **No hard-coded paths**: resolve through config; machine differences belong in the environment.

## Toolchain

`ruff` (line-length 100, double quotes) · `pyright` · `pytest` (gate tests included) · `uv` for
environments · `python -m build` + `twine` for releases.

## Where to look

| Question | File |
|:--|:--|
| How do I use it? | [`README.md`](README.md), [`docs/USAGE.md`](docs/USAGE.md) |
| How does it fit together? | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| What changed, when? | [`docs/CHANGELOG.md`](docs/CHANGELOG.md) |
| How do I release it? | [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) |
| What are the rules? | [`AGENTS.md`](AGENTS.md) |
