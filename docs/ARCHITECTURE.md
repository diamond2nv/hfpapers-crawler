# hfpapers-clawler 系统架构

> 命名哲学: **claw**（利爪）≠ **crawl**（爬行）。
> 包名 `hfpclawer` = HF Papers + claw + er，不是 crawler，比爬虫更快更准。
> 而类名 `HFPapersCrawler` 是真正的 Scrapy 爬虫引擎，名实相符。

## 项目概览

HF Papers 多源论文爬虫 + SQLite 存储引擎 + Crossref 交叉验证 + Scrapy 反爬 + MCP 远程调用。
专注于自动采集 PDE/神经算子/物理信息约束领域的学术论文，集成 LLM-augmented 分类和 arXiv ID 验证。

## 架构层次

```
┌──────────────────────────────────────────────────────┐
│                    CLI (Typer)                        │
│   hfpclawer search | download | convert | full | ...   │
└──────────────────────┬──────────────────────────────-┘
                       │
┌──────────────────────▼──────────────────────────────-┐
│                   MCP Server                          │
│   hfpclawer_search | hfpclawer_download | ... (stdio)  │
└──────────────────────┬──────────────────────────────-┘
                       │
┌──────────────────────▼──────────────────────────────-┐
│                    Scrapy Layer                        │
│  multi_source_spider.py  |  hfspider.py               │
│  ├─ ArxivSearchSpider    ── arXiv API (Atom XML)      │
│  ├─ OpenReviewSpider     ── OpenReview API            │
│  ├─ HFPapersSpider       ── HuggingFace Papers 页面   │
│  └─ MultiSourceSpider    ── 多源统一调度              │
│                                                       │
│  Middleware链: UA随机 | 随机延迟 | 代理轮换 | Cookie池 │
│  Pipeline链: Store→Classify→Export→Download           │
└──────────────────────┬──────────────────────────────-┘
                       │
┌──────────────────────▼──────────────────────────────-┐
│                Paper Store (SQLite)                   │
│  ├─ papers 表 —— 论文主记录 (Snowflake ID)            │
│  ├─ identifiers 表 —— 多标识符映射 (arxiv/doi/...)    │
│  ├─ crossref_cache 表 —— Crossref 查询缓存            │
│  └─ CrossrefClient —— 标题→DOI → arXiv 交叉验证       │
└──────────────────────┬──────────────────────────────-┘
                       │
┌──────────────────────▼──────────────────────────────-┐
│               Core Engine (evolved.py)                │
│  ├─ DedupEngine —— paper_store 适配器                 │
│  ├─ HFPapersCrawler —— HF CLI 搜索 + arXiv 验证       │
│  ├─ RelevanceDetector —— 关键词/短语分级评分           │
│  ├─ PaperDownloader —— PDF 下载 + MD 转换             │
│  └─ 数据目录: data/ | pdfs/ | mds/                    │
└──────────────────────┬──────────────────────────────-┘
                       │
┌──────────────────────▼──────────────────────────────-┐
│               Multi-Source Searcher (sources.py)      │
│  ├─ HfCliSource      —— HF CLI 搜索 (主源)            │
│  ├─ OpenReviewSource —— OpenReview API + 审稿数据     │
│  ├─ PwcApiSource    —— PapersWithCode API + 代码仓库  │
│  └─ ArxivApiSource  —— arXiv API 直接搜索 (备选)     │
└──────────────────────────────────────────────────────-┘
```

## 模块职责

| 模块 | 职责 | 入口 |
|------|------|------|
| `cli.py` | Typer CLI，10+ 子命令 | `hfpclawer` |
| `evolved.py` | 爬虫核心引擎 (HF CLI + arXiv验证) | `HFPapersCrawler` |
| `sources.py` | 多源搜索 (HF/OpenReview/PwC/arXiv) | `get_enabled_sources()` |
| `paper_store.py` | SQLite 存储 + 雪花ID + Crossref | `PaperStore` / `ensure_paper()` |
| `config.py` | YAML 配置 + .env + litellm 价格 | `load_config()` / `get()` |
| `hardware.py` | 硬件探针 (CPU/GPU/降级) | `HardwareProbe` |
| `mcp_server.py` | MCP stdio Server (7 工具) | `run_mcp_server()` |
| `items.py` | Scrapy PaperItem 数据模型 | `PaperItem` |
| `pipelines.py` | Scrapy Pipeline 链 (4 阶段) | `StorePipeline` / `ClassifyPipeline` / ... |
| `middlewares.py` | Scrapy 反爬中间件 (6 层) | `RandomUserAgentMiddleware` / ... |

## 数据流

```
HF CLI搜索 ──→ arXiv ID验证 ──→ 关键词分类 ──→ Dedup检查 ──→ SQLite存储
                    ↓                                            ↓
              PDF下载 ←─── 候选列表JSON ←─── 按相关度排序 ←─── paper_store
                    ↓
              pymupdf4llm → Markdown → mds/ 目录
```

## 存储设计

- **SQLite** (`data/papers.db`): 3 表 — `papers`(主记录)、`identifiers`(多标识符映射)、`crossref_cache`(API缓存)
- **Snowflake ID**: 64-bit, 41bit timestamp + 10bit worker + 12bit sequence, 线程安全
- **JSON 缓存**: `data/candidates_latest.json` — 兼容旧版，快速查询

## 反爬策略

6 层 Scrapy 中间件链：

1. `RandomUserAgentMiddleware` — 每请求随机换 UA (18+ 机型/版本)
2. `RandomDelayMiddleware` — 随机延迟 ±50%
3. `ProxyMiddleware` — 代理轮换 (默认关闭)
4. `CookiesPoolMiddleware` — Cookie 池 (默认关闭)
5. `IntelligentRetryMiddleware` — 智能重试 (429/403/5xx 不同策略)
6. `RobustDownloaderMiddleware` — 连接超时处理 + 指数退避

## 版本历史

- `v3.0.0` — 项目迁移到 `~/Gitlab/Agentic4Sci/hfpapers-clawler/`
- `v2.0.0` — Scrapy 集成 + 反爬中间件 + 分布式去重
- `v1.0.0` — 初始版本: HF CLI 搜索 + JSON 去重 + 关键词分类
