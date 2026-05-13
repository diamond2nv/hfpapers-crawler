# hfpapers-clawler

> 命名哲学: **claw**（利爪）≠ **crawl**（爬行）。
> `hfpclawer` = HF (HuggingFace Papers) + claw (爪) + er (者)
> = "用利爪精准抓取 HF 论文的智能工具"
>
> 不是 crawler（网络爬虫），而是比爬虫更快、更准、更猛的**爪取者** 🦞
> 同系列: OpenClaw（开源爪取工具），Hermes Agent 生态

Multi-source academic paper clawler for PDE / neural operator / physics-informed ML.
SQLite paper_store + Crossref cross-validation + Anti-crawl Scrapy pipelines + MCP server.

---

## Quick Install

```bash
pip install hfpclawer
```

### Dependencies

- **Core** (auto-installed): pyyaml, requests, beautifulsoup4, typer, etc.
- **LLM features** (optional): `pip install hfpclawer[llm]` — for `sniff` / `analyze` commands
- **PDF conversion** (optional): `pip install hfpclawer[pdf]`
- **Scrapy spiders** (optional): `pip install hfpclawer[scrapy]`
- **Dev** (testing): `pip install hfpclawer[dev]`
- **arXiv local search** (optional): `pip install hfpclawer[arxiv]` — requires access to private GitLab repo

### Local Development

```bash
git clone <your-repo>
cd hfpapers-clawler

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Verify
hfpclawer --help
```

### Configuration

Create a `config.yaml` in your project root (see [docs/USAGE.md](docs/USAGE.md) for full reference)
or copy from the default:

```bash
cp config.yaml.example config.yaml
# Edit config.yaml as needed
```

Set environment variables in `.env`:

```bash
DEEPSEEK_API_KEY=sk-...
HF_TOKEN=hf_...
```

---

## CLI Commands

```bash
# Search for new papers
hfpclawer search                    # Default 3 pages, threshold 30
hfpclawer search --max-pages 5      # More pages
hfpclawer search --dry-run          # Show only, don't save

# Full pipeline: search → download → convert
hfpclawer full

# SQLite Paper Store operations
hfpclawer store stats               # Storage statistics
hfpclawer store search              # List all papers
hfpclawer store search --keyword "FNO"
hfpclawer store verify --aid 2301.11167

# Download & convert
hfpclawer download                  # Download top-20 PDFs
hfpclawer convert                   # PDF → Markdown

# MCP Server (for Hermes Agent / OpenCode)
hfpclawer mcp                       # Default port :8765
```

---

## Python API

```python
from hfpapers.paper_store import PaperStore, PaperRecord, ensure_paper

# Create a store
store = PaperStore(db_path="/tmp/papers.db")

# Add a paper
rec = PaperRecord(
    title="Fourier Neural Operator",
    abstract="Learning PDE solution operators with Fourier transforms",
    year=2023,
    source="my_app",
    relevance=90,
)
sf_id = store.upsert_paper(rec)
store.add_identifier(sf_id, "arxiv", "2010.08895")

# Search
papers = store.search_papers("neural operator")
for p in papers:
    print(f"[{p.relevance}] {p.title}")

# Hardware probe
from hfpapers.hardware import HardwareProbe
hw = HardwareProbe()
print(f"Hardware: {hw.summary()}")
```

---

## MCP Server

hfpapers-clawler ships with a built-in MCP server for AI agent integration:

```bash
hfpclawer mcp
```

Register in Hermes Agent `~/.hermes/config.yaml`:

```yaml
mcp:
  servers:
    hfpapers:
      command: "hfpclawer"
      args: ["mcp", "--port", "8765"]
```

Available MCP tools: `hfpclawer_search`, `hfpclawer_download`, `hfpclawer_convert`, `hfpclawer_info`, `hfpclawer_list`, `hfpclawer_stats`, `hfpclawer_full`.

---

## Architecture

```
┌─ CLI (Typer) ─┐  ┌─ MCP Server ─┐
└──────┬────────┘  └──────┬───────┘
       └────────┬──────────┘
                ▼
┌─ Scrapy Layer (Multi-source) ───────────┐
│  ArxivSearchSpider | OpenReviewSpider    │
│  HFPapersSpider | MultiSourceSpider      │
│  Middleware: UA random, delay, proxy...  │
│  Pipeline: Store→Classify→Export→DL     │
└──────────────────┬──────────────────────┘
                   ▼
┌─ Paper Store (SQLite) ──────────────────┐
│  papers (Snowflake ID) | identifiers    │
│  crossref_cache | CrossrefClient        │
└─────────────────────────────────────────┘
```

---

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v           # Run all tests
pytest tests/ --cov=hfpapers  # With coverage
```

---

## License

MIT

## Links

- [Full Usage Guide](docs/USAGE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Developer Guide](docs/DEVELOPMENT.md)
- [Paper Store Reference](docs/paper_store.md)
