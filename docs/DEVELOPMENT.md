# Developer Guide

## Development Environment

```bash
# Activate venv
source venv/bin/activate

# Install development dependencies
pip install -e ".[dev]"

# Code standards
ruff format .                         # Format
ruff check .                          # Lint check
ruff check . --fix                    # Auto-fix

# Type checking
pyright .                             # 0 errors

# Testing
python -m pytest tests/ -v            # Run tests
python -m pytest tests/ -x -v         # Stop on first failure
python -m pytest tests/ -q            # Quiet output
```

## Code Standards

- **Language**: Python 3.10+
- **Format**: Ruff, line-length=100, double quotes
- **Types**: All public functions/methods annotated
- **Logging**: Use `logging.getLogger(__name__)`, no prints
- **Error handling**: Log + graceful degradation, don't silently swallow exceptions

## Testing

### Running Tests

```bash
# All tests
pytest tests/ -v

# By module
pytest tests/test_paper_store.py -v
pytest tests/test_evolved.py -v
pytest tests/test_hardware.py -v
pytest tests/test_sources.py -v
pytest tests/test_config.py -v

# Coverage report
pytest tests/ --cov=hfpapers --cov-report=term-missing

# Slow tests
pytest tests/ -v -k "slow"            # Tests marked as slow
pytest tests/ -v -m "not slow"        # Skip slow tests
```

### Test Strategy

1. **Unit tests** — Test each module independently, mock external dependencies
2. **Integration tests** — paper_store ↔ SQLite ↔ Crossref (mock network)
3. **Snapshot tests** — Config loading, classification edge cases
4. **Hardware adaptive** — Test degradation behavior in different hardware environments

### Fixtures

`tests/conftest.py` provides:

- `test_env` — Auto-isolated temp directory + minimal config.yaml
- `paper_store` — In-memory SQLite PaperStore instance
- `tmp_config` — Customizable temporary config
- `mock_hf_cli` — Mock HF CLI output

## Project Structure

```
hfpapers-clawler/
├── hfpapers/                    # Main package
│   ├── __init__.py
│   ├── cli.py                   # Typer CLI entry point
│   ├── config.py                # Config loading (YAML+env+litellm)
│   ├── evolved.py               # Crawler core engine + dedup + classification + download
│   ├── hardware.py              # Hardware probe (CPU/GPU/downgrade)
│   ├── paper_store.py           # SQLite store + Snowflake ID + Crossref
│   ├── sources.py               # Multi-source search (4 sources)
│   ├── mcp_server.py            # MCP stdio Server
│   ├── items.py                 # Scrapy data model
│   ├── pipelines.py             # Scrapy Pipeline chain
│   ├── middlewares.py           # Scrapy anti-crawl middleware
│   ├── settings.py              # Scrapy settings
│   ├── settings_redis.py        # Distributed Scrapy settings
│   └── spiders/                 # Scrapy spiders
│       ├── hfspider.py          # HF Papers page spider
│       └── multi_source_spider.py  # Multi-source unified spider
├── tests/                       # Test directory
│   ├── __init__.py
│   └── conftest.py              # Shared fixtures
├── config.yaml                  # Main config
├── env.template                 # Environment variable template
├── scrapy.cfg                   # Scrapy config
├── pyproject.toml               # Package config
├── .gitignore
├── docs/                        # Documentation
│   ├── ARCHITECTURE.md
│   ├── USAGE.md
│   └── DEVELOPMENT.md
├── AGENTS.md                    # AI Agent development guide
├── data/                        # Data (gitignored)
├── pdfs/                        # PDFs (gitignored)
├── mds/                         # Markdown (gitignored)
├── logs/                        # Logs (gitignored)
└── md_extracts/                 # Fallback MD extraction (gitignored)
```

## Adding New Features

### Adding a CLI Command

In `hfpapers/cli.py`:

```python
@app.command()
def mycommand(
    param: str = typer.Option("default", "--param", "-p"),
):
    """Description"""
    from hfpapers.module import func
    result = func(param)
    typer.echo(f"Result: {result}")
```

### Adding a New Search Source

1. Inherit `PaperSource` in `hfpapers/sources.py`:
```python
class MySource(PaperSource):
    name = "my_source"
    def search(self, query, category=""):
        ...
```
2. Add to `config.yaml` `search.enabled`
3. Register in `get_enabled_sources()`

### Adding a Scrapy Spider

1. Create spider under `hfpapers/spiders/`
2. Inherit `scrapy.Spider`, output `PaperItem`
3. Register in `settings.py` `SPIDER_MODULES`
4. Optionally add to pipeline chain in `pipelines.py`

## Publishing

```bash
# Build
python -m build

# Check
twine check dist/*

# Publish to PyPI (if needed)
twine upload dist/*
```

## Known Issues and Limitations

1. **PaperWithCode API is deprecated** — `pwc_api` source may return empty results, PwC API has been redirected to HF API
2. **OpenReview nested fields** — content field is a nested dict, needs extraction via `_safe_field()`
3. **Scrapy and paper_store integration** — spider directly calls `ensure_paper()`, bypassing Scrapy pipeline's store stage
4. **Crossref rate limiting** — Free API 50 requests/second, no API key required
5. **HF CLI dependency** — Requires `huggingface_hub` CLI tool to be installed
