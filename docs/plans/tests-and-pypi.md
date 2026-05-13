# hfpapers-clawler 测试 + 示例 + PyPI 发布 Plan

> **For OpenCode (via Hermes OpenCode serve API):** Implement all test files, examples, and finalize for PyPI publishing.

**Goal:** 为 hfpapers-clawler 项目完成完整的测试套件 + 安装使用示例 + PyPI 发布准备

**Architecture:** 项目已存在核心模块（paper_store、evolved、config、hardware、sources），需要补全 tests/ 目录下的单元测试/集成测试，以及 examples/ 下的使用示例。

**Tech Stack:** Python 3.10+, pytest 9.x, pytest-mock, pytest-cov, pyyaml, typer, SQLite3

**Branch Strategy:** 在 master 上增量开发，每完成一个 task 就 commit

---

## 测试清单

| 模块 | 测试文件 | 测试点 |
|------|---------|--------|
| paper_store | `test_paper_store.py` | Snowflake ID CRUD 标识符 交叉验证 统计 |
| config | `test_config.py` | YAML加载 env合并 budget检查 |
| hardware | `test_hardware.py` | 探针检测 CPU/GPU降级 |
| evolved | `test_evolved.py` | DedupEngine RelevanceDetector HFPapersCrawler PageDownloader |
| sources | `test_sources.py` | ARXIV_ID_RE _safe_field 多源调度 |
| cli | `test_cli.py` | 子命令调用 输出格式 |

---

### Task 1: paper_store SQLite CRUD + Snowflake

**Objective:** 测试 PaperStore 的增删改查、Snowflake ID 生成、标识符管理

**Files:**
- Create: `tests/test_paper_store.py`

**Step 1: Write test_paper_store.py**

```python
"""测试 paper_store 模块 — SQLite 存储 + Snowflake ID + 标识符"""
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
        # 按 relevance 降序
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
        # 只有一种类型不应验证
        paper_store.verify_paper(sf_id)
        p = paper_store.get_paper_by_id(sf_id)
        assert not p.verified

        # 添加第二种类型
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
git commit -m "test: paper_store SQLite CRUD + Snowflake ID + 标识符管理"
```

---

### Task 2: config 模块测试

**Objective:** 测试配置加载、环境变量合并、budget 检查

**Files:**
- Create: `tests/test_config.py`

```python
"""测试 config 模块 — YAML 加载 + env 合并 + budget 检查"""
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
        # 创建临时 config.yaml
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
git commit -m "test: config 加载 + env 合并 + budget 检查"
```

---

### Task 3: hardware 模块测试

**Objective:** 测试 HardwareProbe 在不同环境下的探测和降级行为

**Files:**
- Create: `tests/test_hardware.py`

```python
"""测试 hardware 模块 — 探针检测 + 硬件降级"""
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
        # 在没有 CUDA 时 should be False
        if not hw.has_cuda:
            assert hw.use_bert is False
        # 如果没有 sentence-transformers，即使有 CUDA 也 false
        if not hw.has_sentence_transformers:
            assert hw.use_bert is False

    def test_use_pdf_converter(self):
        hw = HardwareProbe()
        # pymupdf4llm 是否可用取决于安装
        from importlib.util import find_spec
        expected = find_spec("pymupdf4llm") is not None
        assert hw.use_pdf_converter == expected
```

**Run + Commit:**
```bash
cd ~/Gitlab/Agentic4Sci/hfpapers-clawler && source venv/bin/activate && python -m pytest tests/test_hardware.py -v --tb=short
git add tests/test_hardware.py
git commit -m "test: HardwareProbe 探测 + 降级行为"
```

---

### Task 4: evolved 核心引擎测试

**Objective:** 测试 DedupEngine、RelevanceDetector、PaperInfo 数据模型

**Files:**
- Create: `tests/test_evolved.py`

```python
"""测试 evolved 模块 — 去重 + 分类 + 爬虫引擎"""
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
git commit -m "test: evolved 去重 + 分类 + 标题相似度"
```

---

### Task 5: sources 多源搜索测试

**Objective:** 测试 ARXIV_ID_RE、_safe_field、去重函数、多源调度

**Files:**
- Create: `tests/test_sources.py`

```python
"""测试 sources 模块 — 多源搜索 + arXiv ID 提取 + 去重"""
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
git commit -m "test: sources 多源搜索 + arXiv ID 提取 + 去重"
```

---

### Task 6: CLI 集成测试

**Objective:** 测试 CLI 子命令的调用和输出格式

**Files:**
- Create: `tests/test_cli.py`

```python
"""测试 CLI — Typer 子命令调用"""
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
git commit -m "test: CLI 子命令集成测试"
```

---

### Task 7: 安装使用示例

**Objective:** 创建 examples/ 目录，包含 pip 安装后使用 demo + Hermes Agent 使用 demo，并向 AGENTS.md 添加 PyPI 发布部分

**Files:**
- Create: `examples/usage_demo.py`
- Create: `examples/hermes_agent_demo.md`
- Modify: `AGENTS.md` (末尾添加 PyPI 发布)

**examples/usage_demo.py:**
```python
#!/usr/bin/env python3
"""
hfpapers-clawler 使用示例

安装:
    pip install hfpclawer

用法:
    python examples/usage_demo.py
"""
import json
import tempfile
from pathlib import Path

# ─── 1. 基础配置 ─────────────────────────────
from hfpapers.config import load_config, get

cfg = load_config()
print(f"1. 配置加载: {len(cfg)} 个顶级键")
print(f"   搜索维度: {get('search.queries')[0]['query']}")
print(f"   相关度阈值: {get('classification.threshold_pass')}")

# ─── 2. Paper Store ──────────────────────────
from hfpapers.paper_store import (
    PaperStore, PaperRecord, PaperIdentifier,
    ensure_paper, store_stats, get_store,
)

# 使用临时数据库
with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
    db_path = f.name
store = PaperStore(db_path=db_path)

# 添加论文
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
print(f"   论文: {store.get_paper_by_id(sf_id).title}")
print(f"   标识符: {store.get_identifiers(sf_id)}")

# ─── 3. 搜索论文 ─────────────────────────────
store.add_paper_from_record(rec) if False else None  # 已存在
papers = store.search_papers("Fourier")
print(f"\n3. 搜索 'Fourier': {len(papers)} 篇")

# ─── 4. 统计 ─────────────────────────────────
stats = store.stats()
print(f"\n4. 统计: {json.dumps(stats, indent=2)}")

# 清理
from pathlib import Path
Path(db_path).unlink(missing_ok=True)
print("\n✅ Demo 运行成功")
```

**examples/hermes_agent_demo.md:**
```markdown
# Hermes Agent 集成示例

## 安装

在 Hermes Agent 环境：

```bash
pip install hfpclawer
```

## MCP Server 集成

在 Hermes Agent 的 `~/.hermes/config.yaml` 中配置：

```yaml
mcp:
  servers:
    hfpapers:
      command: "hfpclawer"
      args: ["mcp", "--port", "8765"]
      env:
        HF_TOKEN: "${HF_TOKEN}"
```

启动后，Hermes Agent 自动发现 MCP 工具：

- `hfpclawer_search`
- `hfpclawer_download`
- `hfpclawer_convert`
- `hfpclawer_info`
- `hfpclawer_list`
- `hfpclawer_stats`
- `hfpclawer_full`

## 使用示例

```
用户: 搜索最新的 PDE 神经算子论文
Hermes: 使用 hfpclawer_search 工具...
结果: 发现 3 篇新论文
- [85] 2010.08895 Fourier Neural Operator
- [75] 2003.03085 DeepONet
- [62] 2104.06458 Physics-Informed Neural Operator
```

## Paper Store 操作

```
用户: 列出论文库
Hermes: 使用 hfpclawer_list 工具...
```

## 全流程 Pipeline

```
用户: 运行全流程管道
Hermes: 使用 hfpclawer_full 工具...
```
```

**Commit:**
```bash
git add examples/
git commit -m "docs: 安装使用示例 + Hermes Agent 集成文档"
```

---

### Task 8: 更新 AGENTS.md — 添加 PyPI 发布

**Objective:** 在 AGENTS.md 末尾添加 PyPI 发布流程

**Modify:** `AGENTS.md` (在末尾追加)

```markdown
## PyPI 发布

### 前置条件

```bash
# 安装构建和发布工具
pip install build twine

# 注册 PyPI 账号
# https://pypi.org/account/register/

# 配置 API token
# 在 ~/.pypirc 中:
# [pypi]
# username = __token__
# password = pypi-xxxxxxxx
```

### 需要用户授权的操作

| 操作 | 需要的授权 | 说明 |
|------|-----------|------|
| GitHub Release | GitHub Token | `gh release create` |
| PyPI 发布 | PyPI API Token | `twine upload` |
| Test PyPI 发布 | Test PyPI Token | `twine upload --repository testpypi` |

### 发布步骤

```bash
# 1. 版本号 bump
# 修改 pyproject.toml 中的 version

# 2. 构建
python -m build

# 3. 先发到 Test PyPI 验证
twine upload --repository testpypi dist/*

# 4. 在 Test PyPI 上验证安装
pip install --index-url https://test.pypi.org/simple/ hfpclawer

# 5. 正式发布
twine upload dist/*

# 6. GitHub Release
gh release create vX.Y.Z --title "hfpapers-clawler vX.Y.Z" --notes "Release notes"
```

### 不用用户授权

- ✅ 代码编写、测试、commit
- ✅ pip install -e . 本地安装
- ✅ 本地运行 `hfpclawer` 命令

> **注意**: PyPI 发布需要 API Token。我（Hermes Agent）不能代你登录 PyPI，但可以帮你构建好 `dist/` 目录，你只需运行 `twine upload dist/*` 并输入 token 即可。
```

**Commit:**
```bash
git add AGENTS.md
git commit -m "docs: 添加 PyPI 发布流程到 AGENTS.md"
```

---

### Task 9: 运行全量测试 + coverage

**Objective:** 运行所有测试，检查覆盖率

```bash
cd ~/Gitlab/Agentic4Sci/hfpapers-clawler && source venv/bin/activate
python -m pytest tests/ -v --tb=short --cov=hfpapers --cov-report=term-missing
```
Expected: all tests PASS, coverage > 60%.

---

## 架构决策

| 决策 | 理由 |
|------|------|
| pytest + pytest-mock | 项目已有 pytest 依赖，避免引入新依赖 |
| 使用 conftest.py fixture | `test_env` 隔离文件系统，`paper_store` 隔离 DB |
| 不 mock psutil | HardwareProbe 依赖 psutil，测试真实环境 |
| CLI 用 Typer CliRunner | 官方推荐，无需子进程调用 |
| Snowflake ID 测试等待 1ms | 保证严格递增，time.sleep(0.001) 足够 |

## 关键路径

```
tests/test_paper_store.py  ← 最核心，12个测试
tests/test_evolved.py      ← 引擎逻辑
tests/test_config.py       ← 配置加载
tests/test_hardware.py     ← 硬件探针
tests/test_sources.py      ← 多源搜索
tests/test_cli.py          ← CLI 集成
examples/usage_demo.py     ← 使用示例
```
