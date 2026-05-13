# Paper Store — SQLite 统一存储引擎

## 概述

`paper_store.py` 是 hfpapers-clawler 的数据核心，提供:

- **Snowflake ID**: 64-bit 分布式唯一 ID 生成器
- **SQLite 3 表**: `papers`(主记录) / `identifiers`(标识符映射) / `crossref_cache`(API缓存)
- **Crossref 交叉验证**: 标题→DOI→arXiv 自动验证
- **线程安全**: `threading.Lock` 保护所有写操作

## Snowflake ID

```python
from hfpapers.paper_store import snowflake_id, snowflake_timestamp

# 生成
sf_id = snowflake_id()           # 64-bit int
sf_id = snowflake_id(worker_id=1)  # 指定 worker

# 解析时间
dt = snowflake_timestamp(sf_id)   # → datetime
```

### 格式

| 1bit | 41bit | 10bit | 12bit |
|------|-------|-------|-------|
| sign | timestamp - epoch | worker_id | sequence |

- Epoch: 2023-11-15 (1700000000000ms)
- 单机: 4096 ID/ms
- 运行寿命: 69 年

## PaperStore 类

### 创建

```python
from hfpapers.paper_store import PaperStore

# 默认路径 (config.yaml paths.data_dir + "papers.db")
store = PaperStore()

# 指定路径
store = PaperStore(db_path="/tmp/test.db")
```

### 写入

```python
from hfpapers.paper_store import PaperRecord

record = PaperRecord(
    title="Fourier Neural Operator",
    abstract="...",
    year=2023,
    source="hf_cli",
    venue="NeurIPS 2023",
    relevance=85,
    has_code=True,
    code_url="https://github.com/zongyi-li/fourier-neural-operator",
)
sf_id = store.upsert_paper(record)
```

### 查询

```python
# 按雪花 ID
paper = store.get_paper_by_id(sf_id)

# 按标识符 (arxiv/doi/etc)
paper = store.get_paper_by_identifier("arxiv", "2301.11167")

# 任意标识符 (自动识别类型)
paper = store.find_paper_by_any_id("2301.11167")   # 自动匹配 arxiv
paper = store.find_paper_by_any_id("10.1038/s41586-024-07116-6")  # 自动匹配 DOI

# 关键词搜索
papers = store.search_papers("neural operator", limit=50)
papers = store.search_papers()  # 全部，按相关度排序
```

### 更新

```python
# 更新指定字段
store.update_paper(sf_id, relevance=90, code_url="...")

# 权限字段:
#   relevance, code_url, venue, has_code, year, abstract, source
```

### 标识符

```python
# 添加标识符映射
store.add_identifier(sf_id, "doi", "10.1038/s41586-024-07116-6",
                     source="crossref", confidence=0.95)

# 获取论文的所有标识符
ids = store.get_identifiers(sf_id)
# → [PaperIdentifier(sf_id=..., id_type="arxiv", id_value="..."), ...]
```

## 交叉验证

### 自动验证

`ensure_paper()` 在创建新论文时自动触发 Crossref 查询：

```python
from hfpapers.paper_store import ensure_paper

sf_id, is_new = ensure_paper(
    arxiv_id="2301.11167",
    title="Fourier Neural Operator",
    source="hf_cli",
    relevance=85,
)
```

### 手动验证

```python
store.verify_paper(sf_id)  # 检查标识符数量 ≥2 种类型
```

### CrossrefClient

```python
from hfpapers.paper_store import CrossrefClient

cr = CrossrefClient(mailto="me@example.com")

# 标题 → DOI 列表
results = cr.title_to_doi("Fourier Neural Operator")

# DOI → 论文详情
details = cr.doi_to_details("10.1007/s11263-024-02021-2")

# 交叉验证: arXiv + title → DOI
result = cr.cross_verify("2301.11167", "Fourier Neural Operator")
```

## 高层接口

全局单例模式，避免重复创建：

```python
from hfpapers.paper_store import get_store, get_crossref, ensure_paper, store_stats

# 获取实例
store = get_store()
cr = get_crossref()

# 统计
stats = store_stats()
# {
#   "papers_total": 100,
#   "papers_verified": 65,
#   "papers_with_code": 42,
#   "identifiers_total": 180,
#   "identifiers_by_type": {"arxiv": 100, "doi": 65, "openreview": 15}
# }
```

## 数据库 Schema

```sql
-- 论文主表
CREATE TABLE papers (
    sf_id       INTEGER PRIMARY KEY,  -- 雪花 ID
    title       TEXT NOT NULL DEFAULT '',
    abstract    TEXT DEFAULT '',
    year        INTEGER DEFAULT 0,
    source      TEXT DEFAULT '',       -- 首次来源
    venue       TEXT DEFAULT '',       -- 会议/期刊
    relevance   INTEGER DEFAULT 0,     -- 相关度 0-100
    has_code    INTEGER DEFAULT 0,
    code_url    TEXT DEFAULT '',
    verified    INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

-- 标识符映射表 (N:1 → papers)
CREATE TABLE identifiers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sf_id       INTEGER NOT NULL,
    id_type     TEXT NOT NULL,          -- arxiv/doi/openreview/issn/pns
    id_value    TEXT NOT NULL,
    source      TEXT DEFAULT '',
    confidence  REAL DEFAULT 1.0,
    verified_at TEXT DEFAULT (datetime('now')),
    UNIQUE(id_type, id_value),
    FOREIGN KEY (sf_id) REFERENCES papers(sf_id)
);

-- Crossref 查询缓存
CREATE TABLE crossref_cache (
    doi         TEXT PRIMARY KEY,
    title       TEXT DEFAULT '',
    arxiv_id    TEXT DEFAULT '',
    venue       TEXT DEFAULT '',
    authors     TEXT DEFAULT '',       -- JSON array
    year        INTEGER DEFAULT 0,
    raw_json    TEXT DEFAULT '',
    queried_at  TEXT DEFAULT (datetime('now'))
);
```

## 去重规则

1. **arXiv ID 唯一**: `identifiers(id_type='arxiv', id_value)`
2. **标识符级别**: 每种 `(id_type, id_value)` 组合唯一
3. **论文级别**: 多条 `PaperInfo` 指向同一 arXiv ID 视为重复
4. **交叉验证**: 不同源提供 ≥2 种标识符类型 → 标记 `verified=1`
