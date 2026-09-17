# hfpclawer — Roadmap (light)

**What this is.** A short, outward-facing view of where the project is going. Detailed planning
lives in [`docs/ROADMAP.md`](docs/ROADMAP.md); what actually shipped lives in
[`docs/CHANGELOG.md`](docs/CHANGELOG.md) (rolling window) and
[`docs/CHANGELOG-archive.md`](docs/CHANGELOG-archive.md) (older entries). Rule for agent
contributors: [`AGENTS.md`](AGENTS.md).

**Function, in one line.** Find, fetch, verify and store academic papers from multiple sources, and
expose them to agents as local, auditable state — a SQLite store plus a CLI and an MCP server.

## Version line

- Versioning is `0.x.y`; `pyproject.toml` is the single source. No rush toward 1.0.
- Development line: `main` (currently `0.18.x`). Public line: `public` → GitHub, versioned on its own
  sequence (`0.17.x`); only one machine is authorized to publish.

## Current line (0.18.x) — the agent-first working set

| Direction | State |
|:--|:--|
| Multi-source registry (Europe PMC, bioRxiv/medRxiv) with registration ≠ enablement | ✅ shipped |
| Verification status machine + conflict → `suspect` (symbolic, 0-LLM) | ✅ shipped |
| Recommendation signals from local state only (`pool` / `rank` / `recommend`) | ✅ shipped |
| Private config overlay (`config.local.yaml`) so public files stay clean | ✅ shipped |
| Mechanical gates: sanitization, changelog coverage, changelog window, doc audit | ✅ shipped |
| Transport that survives a CN network (TCP → QUIC → browser-hint) + resumable fetches | ✅ shipped |

## Next (light, not a commitment)

- Semantic layer (L2a) as a *suggestion* layer with an abstain path — never a gate.
- Wider coverage of the biological/biomedical literature, and cost accounting per run.
- Keep the agent surface small: everything an agent needs should be a documented CLI call with a
  machine-checkable outcome.

## Deliberate non-goals

- **Cloud sync / hosted storage** — the store is local, single-point data; moving it is a
  filesystem/WebDAV concern.
- **Paper notes and annotations** — that is the wiki layer, not the store layer.
- **L6 formal verification (Lean 4)** — interface reserved only; see
  [`docs/use/verify-guide.md`](docs/use/verify-guide.md).
- ~~Paper recommendation~~ — **no longer a non-goal**: `hfpclawer recommend` landed in v0.16.x,
  computed from local signals only.

> History: the v0.6.x-era plan text that used to fill this file is preserved in git
> (`git log -- ROADMAP.md`).
