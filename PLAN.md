# HF Papers 深度爬虫 — Scrapy + requests 混合架构

## 架构设计

```
                ┌──────────────────────────────────┐
                │       hfpapers.spiders            │
                │   HF Papers Spider (Scrapy)      │
                │   → 多维度搜索爬取论文列表        │
                └──────────┬───────────────────────┘
                           │ 论文元数据 (dict)
                           ▼
                ┌──────────────────────────────────┐
                │         Pipeline (pipelines.py)  │
                │ ① 去重过滤 (hfpapers-crawled.json)│
                │ ② 候选列表 → data/candidates.json│
                └──────────┬───────────────────────┘
                           │ arxiv IDs
                           ▼
                ┌──────────────────────────────────┐
                │   Downloader (download_arxiv.py) │
                │ ① requests 下载 PDF(pdfs/)        │
                │ ② pymupdf4llm 转 Markdown(mds/)   │
                │ ③ web_extract 检查 GitHub 代码    │
                └──────────┬───────────────────────┘
                           │ 整理后的论文数据
                           ▼
                ┌──────────────────────────────────┐
                │    Wiki Integrator (集成到llm-wiki)│
                │ ① 更新 index.md + log.md          │
                │ ② 创建概念页/实体页               │
                │ ③ 更新去重记录 (crawled.json)      │
                └──────────────────────────────────┘
```

## 去重策略 (三阶段)
1. **Scrapy 层**: dupefilter + 指纹缓存 (requests指纹)
2. **Pipeline 层**: 对比 hfpapers-crawled.json 中的 arxiv_id
3. **下载层**: 检查 pdfs/ 目录是否已有文件

## 多维度爬取 (federated crawl)
同时爬取 5 个搜索维度，每条结果归一化为统一格式:
- q=PDE+neural+operator+physics-informed
- q=physical+constraint+residual+loss+PDE
- q=AI+4+Science+neural+surrogate
- q=neural+operator+physics+informed (daily papers)
- q=PDE+solution+operators

## 分布式设计 (multi-worker)
- Spider 输出 → Python Queue → 3 个 Downloader worker 并行下载
- worker 1: arxiv PDF 下载
- worker 2: pymupdf4llm 转换
- worker 3: GitHub 代码仓库检查
- 3 个 worker 互不阻塞，通过共享队列解耦

## 预算控制
- 筛选 TOP 20 篇 (不重复)
- 只下载 PDF + 转换 (本地CPU, 0 token)
- 只分析原文摘要 + 代码检查 (控制 LLM token)
- 目标: ≤ ¥20

## Timeline
- 0-5min: Scrapy 爬取 + 去重 → 候选列表
- 5-30min: 并行下载 PDF (3 workers)
- 30-45min: pymupdf4llm 转换
- 45-60min: 代码仓库检查 (requests + web scraping)
- 60-90min: 分析 + wiki 写入
