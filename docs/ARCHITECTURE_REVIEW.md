# hfpapers-crawler 架构审查与优化方案

## 一、当前架构全景

```
config.yaml (search.queries=20, keywords, classification, wiki)
    │
    ▼
search_queue.SearchDispatcher ───→ searcher_registry (arxiv_local, arxiv_api, hf_cli, openreview)
(asyncio PriorityQueue + N workers)        │
    │                                       ▼
    ▼                                  search_results (arXiv ID + title + abstract)
PaperStore (papers.db) ← DedupEngine
    │
    ├── papers table: 3472 records (sf_id, title, abstract, year, source, venue, relevance, has_code, code_url)
    ├── identifiers table: 6618 records (arxiv↔doi cross-ref)
    └── crossref_cache table
    │
    ▼
candidates_latest.json ───→ PaperDownloader ───→ AsyncPdfDownloader
(candidate list)           (sync wrapper)       (aiohttp, 8 concurrent)
    │                           │
    ▼                           ▼
data/pdfs/*.pdf          data/md_extracts/*.md
    │                           │
    ▼                           ▼
convert_pdfs() ──── to_wiki ───→ ~/wiki/raw/papers/{arxiv_id}.md
(pymupdf4llm)
```

## 二、发现的关键问题

### 问题 1: 缺少「paper 处理状态」跟踪 — 核心缺陷

**当前状况：**
- `papers` 表没有 `download_status`、`convert_status`、`wiki_synced` 字段
- 下载/转换状态只能通过 `data/pdfs/*.pdf` 和 `data/md_extracts/*.md` 的文件存在与否推断
- `candidates_latest.json` 每次 `search` 会覆盖，导致候选列表丢失
- 无法从 paper store 直接知道「哪些已下载」「哪些待下载」「哪些转换失败」

**后果：**
- `download` 命令只能从 `candidates_latest.json` 取数据，无法从 paper store 批量拉取
- 3,472 篇入库后，下载队列无法被恢复或分批次处理
- 不知道哪些论文已下载但转换失败，需要重试

### 问题 2: PDF 下载与 paper store 未同步

**当前状况：**
- `PaperDownloader.download_batch()` 下载完 PDF 后，只调 `ensure_paper()` 记录元数据，**不写 `download_status`**
- `AsyncPdfDownloader` 的 PDF/MD 路径硬编码为 `data/pdfs/` 和 `data/mds/`（实际上是 `data/pdf/`？配置是 `paths.pdf_dir=pdfs`，但目录不存在）
- 上次 cron 的 32 篇 PDF 下载到了 `hfpapers-2026-05-12/pdf/`，不是标准路径

### 问题 3: 没有批量后处理队列

**当前状况：**
- 没有「从 paper store 取 N 篇→下载→转 MD→wiki sync」的完整批处理命令
- 没有重试机制记录（下载失败的论文不会自动重试）
- 没有进度持久化（中断后不知道下载到哪了）

### 问题 4: cron 产出与标准路径分裂

- cron 把 PDF 下载到了 `~/wiki/raw/papers/hfpapers-YYYY-MM-DD/pdf/`，而不是 `data/pdfs/`
- `convert_pdfs()` 只扫描 `PDF_DIR`（即 `data/pdfs/`），根本看不到 cron 下载的那些
- 两个路径体系不互通

### 问题 5: 小问题

- `hfpapers/settings_redis.py` 和 `hfpapers/middlewares.py` 引用了 Redis/Scrapy，但不被任何代码使用
- `hfpapers/spiders/` 目录有 Scrapy spider 定义，但实际 pipeline 走的是 `SearchDispatcher` + `HFPapersCrawler`
- `hfpclawer/`（注意拼写：`hfpc**l**awer` vs `hfpc**L**i` CLI entry）下的 `download/` 目录是 Kaggle/OAI 下载器，与论文下载无关
- `paper_store.py` 有 979 行，包含了 Snowflake ID 生成器、PaperStore CRUD、Crossref 客户端、ensure_paper 高层接口——职责太多

## 三、优化方案

### 优化 1: paper 表加处理状态列

在 `papers` 表添加：

```sql
download_status TEXT DEFAULT 'pending',  -- pending/downloading/done/failed
convert_status  TEXT DEFAULT 'pending',  -- pending/converting/done/failed
wiki_synced     INTEGER DEFAULT 0,       -- 0/1
failed_reason   TEXT DEFAULT '',
```

新状态迁移脚本 `scripts/migrate_status.py`：
- 扫描 `data/pdfs/*.pdf` → 标记 download_status='done'
- 扫描 `data/md_extracts/*.md` → 标记 convert_status='done'
- 扫描 `~/wiki/raw/papers/*.md` → 标记 wiki_synced=1

### 优化 2: DownloadQueue — 批量下载作业队列

新增文件 `hfpapers/download_queue.py`：

```python
class DownloadQueue:
    """P0-P1-P2 priority download queue backed by paper_store
    
    Priority tiers:
        P0: Relevance >= 60 (high priority — immediate)
        P1: Relevance 40-59  (medium — batch)
        P2: All remaining    (background — when idle)
    """
    
    def pull_batch(self, batch_size: int = 20, 
                   priority: str = "P0") -> list[PaperRecord]:
        """从 paper store 取一批 pending 论文"""
        
    def mark_downloaded(self, arxiv_id: str):
        """标记下载完成"""
        
    def mark_failed(self, arxiv_id: str, reason: str):
        """标记下载失败"""
        
    def batch_download(self, batch_size: int = 20, 
                       max_retries: int = 2,
                       to_wiki: bool = True) -> dict:
        """完整的「获取队列→下载→转换→wiki sync」流水线"""
```

### 优化 3: `hfpclawer batch` 子命令

```bash
hfpclawer batch [--limit 50] [--priority P0] [--no-wiki]
```

功能：
1. 从 paper store 取 `download_status='pending'` 的论文（按 relevance 排序）
2. 下载 PDF 到 `data/pdfs/`
3. pymupdf4llm 转 MD 到 `data/md_extracts/`
4. `--to-wiki` 同步到 `~/wiki/raw/papers/`
5. 更新 paper store 状态
6. 输出统计：成功/失败/跳过

### 优化 4: 统一路径常量和 cron 集成

- `AsyncPdfDownloader` 使用 `PDF_DIR` / `MD_DIR`（来自 `evolved.py` 的统一常量）
- cron 作业调用 `hfpclawer batch --to-wiki` 而不是自建目录
- `convert_pdfs()` 保持扫描 `PDF_DIR` + 可选 `--to-wiki`

## 四、实施计划

### Phase 1: 数据库迁移
- [ ] `scripts/migrate_status.py` — 加列 + 扫描现有文件回填状态

### Phase 2: DownloadQueue
- [ ] `hfpapers/download_queue.py` — 完整实现
- [ ] 集成到 `PaperDownloader`（或替代它）

### Phase 3: CLI 集成
- [ ] `hfpclawer batch` 子命令
- [ ] 更新 cron 作业配置

### Phase 4: 测试
- [ ] 单元测试（状态迁移、队列拉取）
- [ ] 端到端测试（从 paper store 取 10 篇→下载→转 MD→wiki sync）
