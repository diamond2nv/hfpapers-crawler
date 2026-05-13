# hfpapers-clawler Tests + Examples + PyPI Release Plan

> **For OpenCode (via Hermes OpenCode serve API):** Implement all test files, examples, and finalize for PyPI publishing.

**Goal:** Complete the test suite + installation usage examples + PyPI release preparation for the hfpapers-clawler project

**Architecture:** The project already has core modules (paper_store, evolved, config, hardware, sources). Unit tests / integration tests under tests/ and usage examples under examples/ need to be completed.

**Tech Stack:** Python 3.10+, pytest 9.x, pytest-mock, pytest-cov, pyyaml, typer, SQLite3

**Branch Strategy:** Incremental development on master, commit after each task

---

## Test Checklist

| Module | Test File | Test Points |
|--------|-----------|-------------|
| paper_store | `test_paper_store.py` | Snowflake ID CRUD identifiers cross-validation statistics |
| config | `test_config.py` | YAML loading env merge budget check |
| hardware | `test_hardware.py` | Probe detection CPU/GPU downgrade |
| evolved | `test_evolved.py` | DedupEngine RelevanceDetector HFPapersCrawler PageDownloader |
| sources | `test_sources.py` | ARXIV_ID_RE _safe_field multi-source dispatch |
| cli | `test_cli.py` | Subcommand invocation output format |

---

### Task 1: paper_store SQLite CRUD + Snowflake

**Objective:** Test PaperStore CRUD operations, Snowflake ID generation, identifier management

**Files:**
- Create: `tests/test_paper_store.py`

**Step 1: Write test_paper_store.py**

```python
"""Tests for paper_store module — SQLite storage + Snowflake ID + identifiers"""
import json
import time
from datetime import datetime
from hfpapers.paper_store import (
    snowflake_id, snowflake_timestamp,
    PaperStore, PaperRecord, PaperIdentifier,
    get_store, get_crossref, ensure_paper, store_stats,
)


class TestSnowflakeID:
    def test_snowflake_id_is_int_and_unique(self):
        ids = [snowflake_id() for _ in range(10)]
        assert all(isinstance(i, int) for i in ids)
        assert len(set(ids)) == 10

    def test_snowflake_id_increasing(self):
        id1 = snowflake_id()
        time.sleep(0.001)  # wait 1ms
        id2 = snowflake_id()
        assert id2 > id1

    def test_snowflake_timestamp(self):
        before = datetime.now()
        sf_id = snowflake_id()
        after = datetime.now()
        extracted = snowflake_timestamp(sf_id)
        assert before <= extracted <= after

    def test_snowflake_worker_id(self):
        id1 = snowflake_id(worker_id=0)
        id2 = snowflake_id(worker_id=1)
        assert id1 != id2


class TestPaperStore:
    def test_init_db_creates_tables(self, paper_store: PaperStore):
        import sqlite3
        conn = sqlite3.connect(paper_store.db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {r[0] for r in tables}
        assert "papers" in names
        assert "identifiers" in names
        assert "crossref_cache" in names
        conn.close()

    def test_upsert_and_get_paper(self, paper_store: PaperStore):
        rec = PaperRecord(title="Test Paper", abstract="test", year=2024, source="pytest", relevance=80)
        sf_id = paper_store.upsert_paper(rec)
        assert sf_id > 0

        got = paper_store.get_paper_by_id(sf_id)
        assert got is not None
        assert got.title == "Test Paper"
        assert got.relevance == 80
        assert not got.verified

    def test_get_paper_not_found(self, paper_store: PaperStore):
        got = paper_store.get_paper_by_id(99999)
        assert got is None

    def test_update_paper(self, paper_store: PaperStore):
        sf_id = paper_store.upsert_paper(PaperRecord(title="Title", relevance=50))
        paper_store.update_paper(sf_id, relevance=90, code_url="https://github.com/test")
        got = paper_store.get_paper_by_id(sf_id)
        assert got.relevance == 90
        assert got.code_url == "https://github.com/test"

    def test_add_and_get_identifiers(self, paper_store: PaperStore):
        sf_id = paper_store.upsert_paper(PaperRecord(title="With IDs"))
        paper_store.add_identifier(sf_id, "arxiv", "2301.11167", source="pytest", confidence=0.9)
        paper_store.add_identifier(sf_id, "doi", "10.1234/test", source="crossref")
        ids = paper_store.get_identifiers(sf_id)
        assert len(ids) == 2
        types = {i.id_type for i in ids}
        assert "arxiv" in types
        assert "doi" in types

    def test_add_duplicate_identifier_raises(self, paper_store: PaperStore):
        sf_id = paper_store.upsert_paper(PaperRecord(title="Dup"))
        paper_store.add_identifier(sf_id, "arxiv", "2301.11167")
        import sqlite3
        import pytest
        with pytest.raises(sqlite3.IntegrityError):
            paper_store.add_identifier(sf_id, "arxiv", "2301.11167")

    def test_search_papers_by_keyword(self, paper_store: PaperStore):
        sf1 = paper_store.upsert_paper(PaperRecord(title="Fourier Neural Operator", relevance=90))
        sf2 = paper_store.upsert_paper(PaperRecord(title="DeepONet for PDEs", relevance=70))
        sf3 = paper_store.upsert_paper(PaperRecord(title="Quantum ML", relevance=10))
        paper_store.add_identifier(sf1, "arxiv", "2010.08895")
        paper_store.add_identifier(sf2, "arxiv", "1910.03193")
        paper_store.add_identifier(sf3, "arxiv", "2301.00000")

        results = paper_store.search_papers("neural")
        titles = [r.title for r in results]
        assert "Fourier Neural Operator" in titles

        results_all = paper_store.search_papers()
        assert len(results_all) == 3
        # Sort by relevance descending
        assert results_all[0].relevance >= results_all[1].relevance >= results_all[2].relevance

    def test_find_paper_by_any_id(self, paper_store: PaperStore):
        sf_id = paper_store.upsert_paper(PaperRecord(title="Findable"))
        paper_store.add_identifier(sf_id, "arxiv", "9999.99999")
        paper_store.add_identifier(sf_id, "doi", "10.9999/test")

        by_arxiv = paper_store.find_paper_by_any_id("9999.99999")
        assert by_arxiv is not None
        assert by_arxiv.title == "Findable"

        by_doi = paper_store.find_paper_by_any_id("10.9999/test")
        assert by_doi is not None

    def test_verify_paper(self, paper_store: PaperStore):
        sf_id = paper_store.upsert_paper(PaperRecord(title="Verify Me"))
        paper_store.add_identifier(sf_id, "arxiv", "2301.11167")
        # Only one type should not verify
        paper_store.verify_paper(sf_id)
        p = paper_store.get_paper_by_id(sf_id)
        assert not p.verified

        # Add second type
        paper_store.add_identifier(sf_id, "doi", "10.1234/verify")
        paper_store.verify_paper(sf_id)
        p = paper_store.get_paper_by_id(sf_id)
        assert p.verified

    def test_stats(self, paper_store: PaperStore):
        sf1 = paper_store.upsert_paper(PaperRecord(title="A", relevance=80))
        sf2 = paper_store.upsert_paper(PaperRecord(title="B", relevance=50))
        paper_store.add_identifier(sf1, "arxiv", "2301.00001")
        paper_store.add_identifier(sf2, "arxiv", "2301.00002")
        paper_store.add_identifier(sf1, "doi", "10.1234/a")
        paper_store.verify_paper(sf1)

        s = paper_store.stats()
        assert s["papers_total"] == 2
        assert s["papers_verified"] == 1
        assert s["identifiers_total"] == 3


class TestGetStoreSingleton:
    def test_get_store_returns_same_instance(self):
        s1 = get_store()
        s2 = get_store()
        assert s1 is s2
```

**Step 2: Run tests**

```bash
cd ~/Gitlab/Agentic4Sci/hfpapers-clawler && source venv/bin/activate && python -m pytest tests/test_paper_store.py -v --tb=short 2>&1
```
Expected: ALL 12 test methods PASS.

**Step 3: Check pyright**

```bash
cd ~/Gitlab/Agentic4Sci/hfpapers-clawler && source venv/bin/activate && pyright tests/test_paper_store.py 2>&1 | tail -5
```
Expected: 0 errors.

**Step 4: Commit**

```bash
git add tests/test_paper_store.py
git commit -m "test: paper_store SQLite CRUD + Snowflake ID + identifier management"
```

---

### Task 2: config Module Tests

**Objective:** Test config loading, environment variable merging, budget checking

**Files:**
- Create: `tests/test_config.py`

```python
"""Tests for config module — YAML loading + env merge + budget checks"""
import os
import tempfile
import pytest
from hfpapers.config import load_config, get, load_env, estimate_cost, check_token_budget, check_cost_budget


class TestConfigLoad:
    def test_load_config_returns_dict(self, test_env):
        cfg = load_config(reload=True)
        assert isinstance(cfg, dict)
        assert "search" in cfg
        assert "keywords" in cfg
        assert "classification" in cfg

    def test_get_with_dotpath(self, test_env):
        val = get("search.max_per_dim")
        assert val == 5

    def test_get_default(self, test_env):
        val = get("nonexistent.key", "fallback")
        assert val == "fallback"

    def test_env_override(self, test_env):
        os.environ["DEEPSEEK_API_KEY"] = "sk-test-key"
        cfg = load_config(reload=True)
        assert cfg["env"]["DEEPSEEK_API_KEY"] == "sk-test-key"
        del os.environ["DEEPSEEK_API_KEY"]

    def test_custom_config_path(self):
        # Create temporary config.yaml
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.yaml")
            with open(cfg_path, "w") as f:
                f.write("search:\n  max_per_dim: 99\n")
            os.environ["_TEST_HFPAPERS_CONFIG"] = cfg_path
            cfg = load_config(reload=True)
            assert get("search.max_per_dim") == 99
            del os.environ["_TEST_HFPAPERS_CONFIG"]


class TestBudget:
    def test_estimate_cost_deepseek(self):
        cost = estimate_cost("deepseek/deepseek-chat", 10000, 500)
        assert cost > 0

    def test_check_token_budget_within_limit(self):
        assert check_token_budget(1000, 500)

    def test_check_token_budget_exceeded(self):
        assert not check_token_budget(100000, 50000)

    def test_check_cost_budget_free_model(self):
        assert check_cost_budget("ollama/llama3", 100000, 50000)

    def test_check_cost_budget_exceeded(self):
        assert check_cost_budget("deepseek/deepseek-chat", 500000, 100000, max_cost_usd=0.01) is False
```

**Run + Commit:**
```bash
cd ~/Gitlab/Agentic4Sci/hfpapers-clawler && source venv/bin/activate && python -m pytest tests/test_config.py -v --tb=short
cd ~/Gitlab/Agentic4Sci/hfpapers-clawler && source venv/bin/activate && pyright tests/test_config.py 2>&1 | tail -5
git add tests/test_config.py
git commit -m "test: config loading + env merge + budget check"
```

---

### Task 3: hardware Module Tests

**Objective:** Test HardwareProbe detection and downgrade behavior in different environments

**Files:**
- Create: `tests/test_hardware.py`

```python
"""Tests for hardware module — probe detection + hardware downgrade"""
import pytest
from hfpapers.hardware import HardwareProbe


class TestHardwareProbe:
    def test_probe_has_basic_attrs(self):
        hw = HardwareProbe()
        assert hasattr(hw, "has_torch")
        assert hasattr(hw, "has_cuda")
        assert hasattr(hw, "is_cpu_server")
        assert hw.total_ram_gb > 0

    def test_probe_summary(self):
        hw = HardwareProbe()
        summary = hw.summary()
        assert "RAM:" in summary

    def test_use_bert_property(self):
        hw = HardwareProbe()
        # Should be False without CUDA
        if not hw.has_cuda:
            assert hw.use_bert is False
        # False even with CUDA if no sentence-transformers
        if not hw.has_sentence_transformers:
            assert hw.use_bert is False

    def test_use_pdf_converter(self):
        hw = HardwareProbe()
        # pymupdf4llm availability depends on installation
        from importlib.util import find_spec
        expected = find_spec("pymupdf4llm") is not None
        assert hw.use_pdf_converter == expected
```

**Run + Commit:**
```bash
cd ~/Gitlab/Agentic4Sci/hfpapers-clawler && source venv/bin/activate && python -m pytest tests/test_hardware.py -v --tb=short
git add tests/test_hardware.py
git commit -m "test: HardwareProbe detection + downgrade behavior"
```

---

### Task 4: evolved Core Engine Tests

**Objective:** Test DedupEngine, RelevanceDetector, PaperInfo data model

**Files:**
- Create: `tests/test_evolved.py`

```python
"""Tests for evolved module — dedup + classification + crawl engine"""
import pytest
from hfpapers.evolved import (
    PaperInfo, DedupEngine, RelevanceDetector, HFPapersCrawler,
    PaperDownloader,
)
from hfpapers.paper_store import ensure_paper


class TestPaperInfo:
    def test_default_values(self):
        p = PaperInfo()
        assert p.arxiv_id == ""
        assert p.relevance == 0
        assert p.categories == []
        assert p.has_code == "unknown"

    def test_with_values(self):
        p = PaperInfo(arxiv_id="2301.11167", title="Test", relevance=85)
        assert p.arxiv_id == "2301.11167"
        assert p.relevance == 85


class TestDedupEngine:
    def test_count_starts_as_int(self, test_env):
        engine = DedupEngine()
        assert isinstance(engine.count, int)

    def test_is_duplicate_returns_none_for_new(self, test_env):
        engine = DedupEngine()
        p = PaperInfo(arxiv_id="0000.00000", title="New Paper")
        result = engine.is_duplicate(p)
        assert result is None


class TestRelevanceDetector:
    def test_classify_high_keyword(self, test_env):
        detector = RelevanceDetector()
        p = PaperInfo(title="Fourier Neural Operator for PDEs", abstract="Solving partial differential equations")
        score = detector.classify(p)
        assert score >= 30

    def test_classify_exclude(self, test_env):
        detector = RelevanceDetector()
        p = PaperInfo(title="Quantum Machine Learning", abstract="This paper uses quantum computing")
        score = detector.classify(p)
        assert score == 0

    def test_classify_low_relevance(self, test_env):
        detector = RelevanceDetector()
        p = PaperInfo(title="Weather Forecasting with AI", abstract="Using deep learning")
        score = detector.classify(p)
        assert 0 <= score <= 100

    def test_classify_phrase_high(self, test_env):
        detector = RelevanceDetector()
        p = PaperInfo(title="Physics-Informed Neural Networks Review", abstract="A survey of PINNs")
        score = detector.classify(p)
        assert score >= 15

    def test_threshold_pass(self, test_env):
        detector = RelevanceDetector()
        assert detector.threshold_pass == 30


class TestHFPapersCrawler:
    def test_title_similarity(self):
        sim = HFPapersCrawler._title_similarity(
            "Fourier Neural Operator for PDEs",
            "Fourier Neural Operator for Partial Differential Equations",
        )
        assert 0.3 < sim <= 1.0

    def test_title_similarity_unrelated(self):
        sim = HFPapersCrawler._title_similarity(
            "Quantum Physics",
            "Weather Forecasting",
        )
        assert sim < 0.5

    def test_title_similarity_identical(self):
        sim = HFPapersCrawler._title_similarity(
            "Neural Operator", "neural operator!"
        )
        assert sim > 0.7

    def test_title_similarity_empty(self):
        sim = HFPapersCrawler._title_similarity("", "")
        assert sim == 0.0


class TestPaperDownloader:
    def test_make_session(self):
        engine = DedupEngine()
        downloader = PaperDownloader(dedup=engine)
        assert downloader.session is not None
        assert "Mozilla" in downloader.session.headers["User-Agent"]
```

**Run + Commit:**
```bash
cd ~/Gitlab/Agentic4Sci/hfpapers-clawler && source venv/bin/activate && python -m pytest tests/test_evolved.py -v --tb=short
git add tests/test_evolved.py
git commit -m "test: evolved dedup + classification + title similarity"
```

---

### Task 5: Sources Multi-Source Search Tests

**Objective:** Test ARXIV_ID_RE, _safe_field, dedup functions, multi-source dispatch

**Files:**
- Create: `tests/test_sources.py`

```python
"""Tests for sources module — multi-source search + arXiv ID extraction + dedup"""
import pytest
from hfpapers.sources import (
    ARXIV_ID_RE, _safe_field,
    deduplicate, get_enabled_sources,
    SourcePaper, HfCliSource, OpenReviewSource, PwcApiSource, ArxivApiSource,
)


class TestArxivIdRegex:
    def test_match_standard(self):
        m = ARXIV_ID_RE.search("2301.11167")
        assert m is not None
        assert m.group(1) == "2301.11167"

    def test_match_with_version(self):
        m = ARXIV_ID_RE.search("2301.11167v3")
        assert m is not None
        assert m.group(1) == "2301.11167"

    def test_match_5_digit(self):
        m = ARXIV_ID_RE.search("2301.12345")
        assert m is not None

    def test_match_in_url(self):
        m = ARXIV_ID_RE.search("https://arxiv.org/abs/2301.11167v2")
        assert m is not None
        assert m.group(1) == "2301.11167"

    def test_no_match(self):
        m = ARXIV_ID_RE.search("not-an-arxiv-id")
        assert m is None

    def test_no_match_short(self):
        m = ARXIV_ID_RE.search("123.456")
        assert m is None


class TestSafeField:
    def test_plain_string(self):
        assert _safe_field({"title": "Paper Title"}, "title") == "Paper Title"

    def test_nested_value_dict(self):
        assert _safe_field({"title": {"value": "Nested Title"}}, "title") == "Nested Title"

    def test_nested_content_dict(self):
        assert _safe_field({"abstract": {"content": "Abstract text"}}, "abstract") == "Abstract text"

    def test_missing_key(self):
        assert _safe_field({"other": "value"}, "nonexistent") == ""


class TestDeduplicate:
    def test_no_duplicates(self):
        papers = [
            SourcePaper(arxiv_id="2301.00001", title="A"),
            SourcePaper(arxiv_id="2301.00002", title="B"),
        ]
        result = deduplicate(papers)
        assert len(result) == 2

    def test_duplicates_removed(self):
        papers = [
            SourcePaper(arxiv_id="2301.00001", title="A"),
            SourcePaper(arxiv_id="2301.00001", title="A duplicate"),
            SourcePaper(arxiv_id="2301.00002", title="B"),
        ]
        result = deduplicate(papers)
        assert len(result) == 2
        assert result[0].title == "A"

    def test_empty_list(self):
        assert deduplicate([]) == []


class TestGetEnabledSources:
    def test_returns_list(self, test_env):
        sources = get_enabled_sources()
        assert len(sources) > 0
        assert all(hasattr(s, "search") for s in sources)


class TestSourcePaper:
    def test_defaults(self):
        p = SourcePaper()
        assert p.arxiv_id == ""
        assert p.reviews == []
        assert p.source == ""
```

**Run + Commit:**
```bash
cd ~/Gitlab/Agentic4Sci/hfpapers-clawler && source venv/bin/activate && python -m pytest tests/test_sources.py -v --tb=short
git add tests/test_sources.py
git commit -m "test: sources multi-source search + arXiv ID extraction + dedup"
```

---

### Task 6: CLI Integration Tests

**Objective:** Test CLI subcommand invocation and output format

**Files:**
- Create: `tests/test_cli.py`

```python
"""Tests for CLI — Typer subcommand invocation"""
from typer.testing import CliRunner
from hfpapers.cli import app

runner = CliRunner()


class TestCLI:
    def test_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output
        assert "hfpclawer" in result.output

    def test_config(self, test_env):
        result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        assert "search" in result.output

    def test_dedup(self, test_env):
        result = runner.invoke(app, ["dedup"])
        assert result.exit_code == 0

    def test_search_dry_run(self, test_env):
        result = runner.invoke(app, ["search", "--dry-run"])
        assert result.exit_code == 0

    def test_store_stats(self, test_env):
        result = runner.invoke(app, ["store", "stats"])
        assert result.exit_code == 0

    def test_list_empty(self):
        result = runner.invoke(app, ["list"])
        assert result.exit_code in (0, 1)

    def test_info_not_found(self):
        result = runner.invoke(app, ["info", "9999.99999"])
        assert result.exit_code == 1

    def test_convert_no_pdfs(self, test_env):
        result = runner.invoke(app, ["convert"])
        assert result.exit_code in (0, 1)
```

**Run + Commit:**
```bash
cd ~/Gitlab/Agentic4Sci/hfpapers-clawler && source venv/bin/activate && python -m pytest tests/test_cli.py -v --tb=short
git add tests/test_cli.py
git commit -m "test: CLI subcommand integration tests"
```

---

### Task 7: Installation Usage Examples

**Objective:** Create examples/ directory with pip installation demo + Hermes Agent usage demo, and add PyPI release section to AGENTS.md

**Files:**
- Create: `examples/usage_demo.py`
- Create: `examples/hermes_agent_demo.md`
- Modify: `AGENTS.md` (append PyPI release)

**examples/usage_demo.py:**
```python
#!/usr/bin/env python3
"""
hfpapers-clawler usage example

Installation:
    pip install hfpclawer

Usage:
    python examples/usage_demo.py
"""
import json
import tempfile
from pathlib import Path

# ─── 1. Basic Configuration ─────────────────────────
from hfpapers.config import load_config, get

cfg = load_config()
print(f"1. Config loaded: {len(cfg)} top-level keys")
print(f"   Search dimension: {get('search.queries')[0]['query']}")
print(f"   Relevance threshold: {get('classification.threshold_pass')}")

# ─── 2. Paper Store ─────────────────────────────────
from hfpapers.paper_store import (
    PaperStore, PaperRecord, PaperIdentifier,
    ensure_paper, store_stats, get_store,
)

# Use a temporary database
with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
    db_path = f.name
store = PaperStore(db_path=db_path)

# Add a paper
rec = PaperRecord(
    title="Fourier Neural Operator for PDEs",
    abstract="Learning PDE solution operators with Fourier transforms",
    year=2023,
    source="demo",
    relevance=90,
)
sf_id = store.upsert_paper(rec)
store.add_identifier(sf_id, "arxiv", "2010.08895", source="demo")

print(f"\n2. Paper Store: sf_id={sf_id}")
print(f"   Paper: {store.get_paper_by_id(sf_id).title}")
print(f"   Identifiers: {store.get_identifiers(sf_id)}")

# ─── 3. Search Papers ───────────────────────────────
store.add_paper_from_record(rec) if False else None  # Already exists
papers = store.search_papers("Fourier")
print(f"\n3. Search 'Fourier': {len(papers)} papers")

# ─── 4. Statistics ──────────────────────────────────
stats = store.stats()
print(f"\n4. Statistics: {json.dumps(stats, indent=2)}")

# Cleanup
from pathlib import Path
Path(db_path).unlink(missing_ok=True)
print("\n✅ Demo ran successfully")
```

**examples/hermes_agent_demo.md:**
```markdown
# Hermes Agent Integration Example

## Installation

In a Hermes Agent environment:

```bash
pip install hfpclawer
```

## MCP Server Integration

Configure in Hermes Agent's `~/.hermes/config.yaml`:

```yaml
mcp:
  servers:
    hfpapers:
      command: "hfpclawer"
      args: ["mcp", "--port", "8765"]
      env:
        HF_TOKEN: "${HF_TOKEN}"
```

After startup, Hermes Agent automatically discovers the MCP tools:

- `hfpclawer_search`
- `hfpclawer_download`
- `hfpclawer_convert`
- `hfpclawer_info`
- `hfpclawer_list`
- `hfpclawer_stats`
- `hfpclawer_full`

## Usage Examples

```
User: Search for the latest PDE neural operator papers
Hermes: Using hfpclawer_search tool...
Results: Found 3 new papers
- [85] 2010.08895 Fourier Neural Operator
- [75] 2003.03085 DeepONet
- [62] 2104.06458 Physics-Informed Neural Operator
```

## Paper Store Operations

```
User: List the paper store
Hermes: Using hfpclawer_list tool...
```

## Full Pipeline

```
User: Run the full pipeline
Hermes: Using hfpclawer_full tool...
```
```

**Commit:**
```bash
git add examples/
git commit -m "docs: installation usage examples + Hermes Agent integration documentation"
```

---

### Task 8: Update AGENTS.md — Add PyPI Release

**Objective:** Append PyPI release process to AGENTS.md

**Modify:** `AGENTS.md` (append at end)

```markdown
## PyPI Release

### Prerequisites

```bash
# Install build and release tools
pip install build twine

# Register a PyPI account
# https://pypi.org/account/register/

# Configure API token
# In ~/.pypirc:
# [pypi]
# username = __token__
# password = pypi-xxxxxxxx
```

### Actions Requiring User Authorization

| Action | Authorization Needed | Description |
|--------|--------------------|-------------|
| GitHub Release | GitHub Token | `gh release create` |
| PyPI Release | PyPI API Token | `twine upload` |
| Test PyPI Release | Test PyPI Token | `twine upload --repository testpypi` |

### Release Steps

```bash
# 1. Bump version number
# Modify version in pyproject.toml

# 2. Build
python -m build

# 3. First publish to Test PyPI for verification
twine upload --repository testpypi dist/*

# 4. Verify installation from Test PyPI
pip install --index-url https://test.pypi.org/simple/ hfpclawer

# 5. Official release
twine upload dist/*

# 6. GitHub Release
gh release create vX.Y.Z --title "hfpapers-clawler vX.Y.Z" --notes "Release notes"
```

### No User Authorization Needed

- ✅ Code writing, testing, committing
- ✅ Local `pip install -e .` installation
- ✅ Local execution of `hfpclawer` commands

> **Note**: PyPI release requires an API token. I (Hermes Agent) cannot log into PyPI on your behalf, but I can build the `dist/` directory — you just need to run `twine upload dist/*` and enter the token.
```

**Commit:**
```bash
git add AGENTS.md
git commit -m "docs: add PyPI release process to AGENTS.md"
```

---

### Task 9: Run Full Test Suite + Coverage

**Objective:** Run all tests, check coverage

```bash
cd ~/Gitlab/Agentic4Sci/hfpapers-clawler && source venv/bin/activate
python -m pytest tests/ -v --tb=short --cov=hfpapers --cov-report=term-missing
```
Expected: all tests PASS, coverage > 60%.

---

## Architecture Decisions

| Decision | Reason |
|----------|--------|
| pytest + pytest-mock | Project already has pytest dependency, avoids introducing new dependencies |
| Using conftest.py fixture | `test_env` isolates filesystem, `paper_store` isolates DB |
| No mock for psutil | HardwareProbe depends on psutil, test on real environment |
| CLI uses Typer CliRunner | Official recommendation, no subprocess invocation needed |
| Snowflake ID test waits 1ms | Guarantees strict increment, time.sleep(0.001) is sufficient |

## Key Paths

```
tests/test_paper_store.py  ← Core, 12 tests
tests/test_evolved.py      ← Engine logic
tests/test_config.py       ← Config loading
tests/test_hardware.py     ← Hardware probe
tests/test_sources.py      ← Multi-source search
tests/test_cli.py          ← CLI integration
examples/usage_demo.py     ← Usage example
```
