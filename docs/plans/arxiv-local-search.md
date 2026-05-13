# arXiv Local Search Service — hfpapers-clawler 本地 arXiv 元数据检索引擎

## 数据源

- **Kaggle**: [arXiv Academic Paper Dataset](https://www.kaggle.com/datasets/Cornell-University/arxiv)
- **论文**: 2,689,088 篇（1986-04 ~ 2025-03，每周更新）
- **格式**: JSON（每行一条记录）
- **大小**: 4.58G（压缩）/ ~15G（解压）
- **字段**: id(=arxiv ID), title, authors, abstract, categories, journal_ref, doi, update_date

## 架构

```
arxiv_metadata.json (Kaggle)
        │
        ▼
   raw_import.py       ← 解析 JSON Lines，建倒排索引
        │
        ▼
   sqlite_papers.db    ← SQLite FTS5 全文搜索引擎
        │
        ▼
   arxiv_search.py     ← Python API: search(query, limit, year_filter)
        │
        ▼
   hfpapers             ← 集成到 sources.py 作为 fallback 源
```

## 文件

| 文件 | 用途 |
|------|------|
| `hfpapers/arxiv_search.py` | 本地 FTS5 搜索引擎 API |
| `hfpapers/spiders/arxiv_local_spider.py` | Scrapy spider 对接本地搜索 |
| `scripts/import_arxiv_metadata.py` | 导入 Kaggle JSON → SQLite FTS5 |
| `data/arxiv_meta.db` | 生成的 FTS5 数据库（~500MB） |

## 集成方式

`config.yaml` 新增：

```yaml
sources:
  arxiv_local:
    db_path: "data/arxiv_meta.db"
    enable: true
    fallback_priority: 2  # low priority, use as complement
```

`sources.py` 新增 `ArxivLocalSource`，在 API 搜索失败时自动降级。
