# hfpapers-clawler 系统架构

> 命名哲学: **claw**（利爪）≠ **crawl**（爬行）。
> 包名 `hfpclawer` = HF Papers + claw + er，不是 crawler — 比网络爬虫更快、更准。
> 而类名 `HFPapersCrawler` 是实际的 Scrapy 爬虫引擎，名副其实。

## 项目概览

HF Papers 多源论文爬虫 + SQLite 存储引擎 + Crossref 交叉验证 + Scrapy 反爬 + MCP 远程调用。
专注于 PDE / 神经算子 / 物理信息约束领域学术论文的自动化收集，结合 LLM 增强分类和 arXiv ID 验证。

## 架构分层

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
│                    Scrapy 层                           │
│  multi_source_spider.py  |  hfspider.py               │
│  ├─ ArxivSearchSpider    ── arXiv API (Atom XML)      │
│  ├─ OpenReviewSpider     ── OpenReview API            │
│  ├─ HFPapersSpider       ── HuggingFace Papers 页面   │
│  └─ MultiSourceSpider    ── 多源统一调度              │
│                                                       │
│  中间件链: 随机 UA | 随机延迟 | 代理                  │
│  管道链: 存储→分类→导出→下载                          │
└──────────────────────┬──────────────────────────────-┘
                       │
┌──────────────────────▼──────────────────────────────-┐
│                Paper Store (SQLite)                   │
│  ├─ papers 表 — 主论文记录（雪花 ID）                  │
│  ├─ identifiers 表 — 多标识符映射                      │
│  ├─ crossref_cache 表 — Crossref 查询缓存              │
│  └─ CrossrefClient — 标题→DOI→arXiv 交叉验证           │
└──────────────────────┬──────────────────────────────-┘
                       │
┌──────────────────────▼──────────────────────────────-┐
│               核心引擎 (evolved.py)                    │
│  ├─ DedupEngine — paper_store 适配器                   │
│  ├─ HFPapersCrawler — HF CLI 搜索 + arXiv 验证        │
│  ├─ RelevanceDetector — 关键词/短语分级评分            │
│  ├─ PaperDownloader — PDF 下载 + MD 转换              │
│  └─ 数据目录: data/ | pdfs/ | mds/                    │
└──────────────────────┬──────────────────────────────-┘
                       │
┌──────────────────────▼──────────────────────────────-┐
│               多源搜索引擎 (sources.py)                │
│  ├─ HfCliSource      — HF CLI 搜索（主源）            │
│  ├─ OpenReviewSource — OpenReview API + 审稿数据      │
│  ├─ PwcApiSource     — PapersWithCode API + 代码仓库  │
│  └─ ArxivApiSource   — arXiv API 直接搜索（备用）     │
└──────────────────────────────────────────────────────-┘
```

## 模块职责

| 模块 | 职责 | 入口 |
|------|------|------|
| `cli.py` | Typer CLI，10+ 子命令 | `hfpclawer` |
| `evolved.py` | 爬虫核心引擎（HF CLI + arXiv 验证） | `HFPapersCrawler` |
| `sources.py` | 多源搜索（HF/OpenReview/PwC/arXiv） | `get_enabled_sources()` |
| `paper_store.py` | SQLite 存储 + 雪花 ID + Crossref | `PaperStore` / `ensure_paper()` |
| `config.py` | YAML 配置 + .env + litellm 价格 | `load_config()` / `get()` |
| `hardware.py` | 硬件探针（CPU/GPU/降级） | `HardwareProbe` |
| `mcp_server.py` | MCP stdio Server（7 工具） | `run_mcp_server()` |
| `items.py` | Scrapy PaperItem 数据模型 | `PaperItem` |
| `pipelines.py` | Scrapy 管道链（4 阶段） | `StorePipeline` / `ClassifyPipeline` / ... |
| `middlewares.py` | Scrapy 反爬中间件（6 层） | `RandomUserAgentMiddleware` / ... |

## 数据流

```
HF CLI 搜索 ──→ arXiv ID 验证 ──→ 关键词分类 ──→ 去重检查 ──→ SQLite 存储
                    ↓                                           ↓
              PDF 下载 ←─── 候选列表 JSON ←─── 按相关度排序 ←─── paper_store
                    ↓
              pymupdf4llm → Markdown → mds/ 目录
```

## 存储设计

- **SQLite** (`data/papers.db`): 3 张表 — `papers`（主记录）、`identifiers`（多标识符映射）、`crossref_cache`（API 缓存）
- **雪花 ID**: 64 位，41bit 时间戳 + 10bit 工作节点 + 12bit 序列号，线程安全
- **JSON 缓存**: `data/candidates_latest.json` — 兼容旧版，快速查询

## 反爬策略

6 层 Scrapy 中间件链:

1. `RandomUserAgentMiddleware` — 每请求随机 UA（18+ 型号/版本）
2. `RandomDelayMiddleware` — 随机延迟 ±50%
3. `ProxyMiddleware` — 代理轮换（默认关闭）
4. `CookiesPoolMiddleware` — Cookie 池（默认关闭）
5. `IntelligentRetryMiddleware` — 智能重试（429/403/5xx 不同策略）
6. `RobustDownloaderMiddleware` — 连接超时 + 指数退避

## 版本历史

- `v3.0.0` — 项目迁移到 `~/Gitlab/Agentic4Sci/hfpapers-crawler/`
- `v2.0.0` — Scrapy 集成 + 反爬中间件 + 分布式去重
- `v1.0.0` — 初始版本: HF CLI 搜索 + JSON 去重 + 关键词分类
