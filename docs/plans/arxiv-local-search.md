# arXiv Local Search Service — hfpapers-clawler Local arXiv Metadata Search Engine

## Data Source

- **Kaggle**: [arXiv Academic Paper Dataset](https://www.kaggle.com/datasets/Cornell-University/arxiv)
- **Papers**: 2,689,088 (1986-04 ~ 2025-03, updated weekly)
- **Format**: JSON (one record per line)
- **Size**: 4.58G (compressed) / ~15G (decompressed)
- **Fields**: id(=arxiv ID), title, authors, abstract, categories, journal_ref, doi, update_date

## Architecture

```
arxiv_metadata.json (Kaggle)
        │
        ▼
   raw_import.py       ← Parse JSON Lines, build inverted index
        │
        ▼
   sqlite_papers.db    ← SQLite FTS5 full-text search engine
        │
        ▼
   arxiv_search.py     ← Python API: search(query, limit, year_filter)
        │
        ▼
   hfpapers             ← Integrated into sources.py as fallback source
```

## Files

| File | Purpose |
|------|---------|
| `hfpapers/arxiv_search.py` | Local FTS5 search engine API |
| `hfpapers/spiders/arxiv_local_spider.py` | Scrapy spider for local search integration |
| `scripts/import_arxiv_metadata.py` | Import Kaggle JSON → SQLite FTS5 |
| `data/arxiv_meta.db` | Generated FTS5 database (~500MB) |

## Integration

New additions to `config.yaml`:

```yaml
sources:
  arxiv_local:
    db_path: "data/arxiv_meta.db"
    enable: true
    fallback_priority: 2  # low priority, use as complement
```

Add `ArxivLocalSource` in `sources.py`, which auto-degrades when API search fails.
