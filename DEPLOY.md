# Deploying hfpclawer (light)

**What you are deploying.** A local CLI plus a SQLite paper store — no server, no daemon required.
`hfpclawer` finds, fetches, verifies and stores papers, and exposes them to an agent through the CLI
and an MCP server. Everything it writes is local and inspectable.

## 1. Requirements

- Python **≥ 3.10**
- A writable data directory (default: `./data`)
- Optional: `aioquic` for the QUIC transport (needed on networks that reset arXiv TCP connections)

## 2. Install

```bash
pip install "hfpclawer[pdf,quic]"     # add [rank] for the learned re-ranking layer
hfpclawer init                        # writes config.yaml + .env.template in the current directory
hfpclawer version
```

> Deeply customised setups: keep machine- or person-specific values in the gitignored
> `config.local.yaml`, which deep-merges over `config.yaml`. Real names, ORCIDs and query lists
> belong there, never in the tracked file.

## 3. Smoke test (do this before trusting a deployment)

```bash
hfpclawer source-list                        # adapters exist at all
hfpclawer fetch 2310.10688 --kind pdf        # transport ladder + sha256 audit line
hfpclawer store status                       # store is readable, migrations applied
hfpclawer check-new                          # 0-token change detection (cron entry point)
```

`hfpclawer fetch` prints a sha256 and appends an audit row to `data/download_audit.jsonl`; fetching
the same id twice over different channels and comparing hashes is the integrity check.

## 4. What lives where

State lives in one **state root**, resolved once at import: the repository when you run from a
checkout, and the platform's user directories when installed from a wheel
(`$XDG_DATA_HOME/hfpclawer` → `~/.local/share/hfpclawer`, configuration in
`$XDG_CONFIG_HOME/hfpclawer` → `~/.config/hfpclawer`). `HFPCLAWER_STATE_DIR` and
`HFPCLAWER_CONFIG_DIR` override it outright. Nothing is ever written inside a wheel's
`site-packages` — see `hfpapers/paths.py`.

| Path (under the state root) | Content |
|:--|:--|
| `data/papers.db` | the store (SQLite): papers, identifiers, verification state |
| `data/download_audit.jsonl` | append-only acquisition audit (transport, bytes, sha256, ms) |
| `data/positive_pool.jsonl` | local training signal for the optional ranker (gitignored) |
| `pdfs/`, `mds/` | fetched PDFs and converted Markdown |
| `config.yaml` / `config.local.yaml` | public configuration / private overlay |

## 5. Optional: several machines on one LAN

Simplest shape: each machine runs independently and shares only the dedup file (sync it with
rsync/WebDAV/git). Nothing else needs to be shared, and no coordination service is required.

> The older Scrapy + Redis queue design (scrapy-redis, `scrapy crawl multi_source`) is **not
> implemented** in this codebase — see [`ROADMAP.md`](ROADMAP.md) non-goals and
> [`docs/DISTRIBUTED.md`](docs/DISTRIBUTED.md). Use the independent-node shape above.

## 6. Agent integration

- **0-token monitoring**: `hfpclawer check-new` compared against its own last output is the cron
  gate — stable output means "nothing changed, do not wake the LLM".
- **MCP**: `hfpclawer mcp` serves the store to an agent host over stdio.
- **Contract**: agents should treat the CLI as the interface; if a capability is only reachable from
  Python internals, it is not deployed yet.
