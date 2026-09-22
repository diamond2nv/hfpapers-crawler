# hfpapers-clawler 使用指南

## 安装

```bash
# 克隆项目
git clone https://github.com/diamond2nv/hfpapers-crawler
cd hfpapers-crawler

# 创建虚拟环境 (Python >= 3.10)
python -m venv venv
source venv/bin/activate

# 安装依赖
pip install -e .          # 基础安装
pip install -e ".[scrapy]"  # 含 Scrapy（需额外依赖）
pip install -e ".[dev]"     # 含开发工具
pip install -e ".[arxiv]"   # 含 arXiv 本地检索（OAI-PMH 或 Kaggle — 见 [kaggle-metadata.md](../kaggle-metadata.md)）

### 用 uv 装 CLI（推荐）—— 轻装起步，事后按需加装

```bash
uv tool install hfpclawer        # 只装核心；CLI 住在自己的环境里，不污染项目 venv
# 用熟之后再上更重的功能，两种方式都实测可用：
uv tool install --force "hfpclawer[nlp]"                              # 按 extra 重解析
uv pip install --python "$(uv tool dir)/hfpclawer/bin/python" spacy   # 往已装环境注入单个包
```

> ⚠️ uv tool 环境**不含 pip**（`…/bin/python -m pip` 会报 No module named pip）——不是障碍：
> 用 `uv pip install --python "$(uv tool dir)/hfpclawer/bin/python" <包>`，uv 不需要环境里有 pip。
> ⚠️ `uvx hfpclawer` 可能**悄悄跑旧版**：`uv tool run` 优先复用已安装的 tool 环境，`--refresh` 也改不了。
> 换版本用 `uv tool upgrade hfpclawer` ／ `uv tool install --force hfpclawer` ／ 显式 `uvx hfpclawer@0.19.0`。

# 可选 extras —— 全部是惰性加载：缺失时功能降级并提示该装什么
#   [quic]   HTTP/3 传输（aioquic）—— 部分网络下唯一能到达 arXiv 的通道
#   [nlp]    spaCy + en_core_web_sm，用于关键词 / 标签 / 语义增强
#   [zotero] pyzotero，访问本地 Zotero API 时需要
#   [graph]  networkx + geopy，引文图谱命令需要
#   [llm]    litellm，仅可选的大模型辅助路径需要
# ⚠️ 从 PyPI 装：`pip install "hfpclawer[nlp]"` 只给 spaCy、**不含模型**——模型 wheel 是
# 直链依赖，PyPI 不接受。需自行补：`python -m spacy download en_core_web_sm`
# （也接受 md，且两者都在时优先用 md）。

# 配置
cp .env.template .env
# 编辑 .env 填入 API Keys

# 验证
hfpclawer --help
```

## CLI 命令

`hfpclawer` 提供 10+ 子命令：

### 搜索与爬取

```bash
# 搜索新论文（HF CLI → arXiv 验证 → 关键词分类）
hfpclawer search                     # 默认: 3 页，阈值 30
hfpclawer search --max-pages 5       # 搜索更多
hfpclawer search --threshold 50      # 更高相关度阈值
hfpclawer search --dry-run           # 仅显示，不保存

# 全流程: search → download → convert
hfpclawer full

# 多源搜索（配置驱动）
hfpclawer crawl
```

### 生物医学数据源（v0.18+）

Europe PMC、bioRxiv 与 medRxiv 已注册为适配器。**注册不等于启用** —— 需要把名字加入
`config.yaml` 的 `search.enabled`：

```yaml
search:
  enabled: [hf_cli, arxiv_api, europepmc, biorxiv, medrxiv]
```

任何个人或第三方数据（检索式、真实姓名、ORCID）都应放进被 gitignore 的
`config.local.yaml`，它会深度合并覆盖 `config.yaml`；被跟踪的文件只保留
`search.biomed_queries: []` 作为声明占位。
瞬态失败由 `anti_crawl` 的共享策略重试（`max_retries` / `retry_http_codes` /
`retry_delay_base`）—— 单次 503 不再静默丢掉一整批。

### 存储管理

```bash
# SQLite Paper Store 操作
hfpclawer store stats                # 存储统计
hfpclawer store search --keyword "FNO"  # 搜索论文
hfpclawer store search               # 列出所有论文
hfpclawer store ensure --aid 2301.11167 --title "..."  # 确保论文存在
hfpclawer store ensure --aid 2301.11167 --accept-unverified  # 有意接受低置信度的 DOI
hfpclawer store verify --aid 2301.11167 --title "..."  # Crossref 交叉验证
hfpclawer store ids --aid 2301.11167 # 查看论文标识符
```

### 下载与转换

```bash
# 下载候选论文 PDF
hfpclawer download                    # 下载 TOP-20
hfpclawer download --limit 50         # 下载更多

# PDF → Markdown 转换
hfpclawer convert                     # 批量 pymupdf4llm 转换

# 列出论文
hfpclawer list                        # 列出已爬取论文
hfpclawer info 2301.11167             # 单篇论文详情
```

### 直接获取 + 网络逃生 (v0.16.11+)

`fetch` 是已知 arXiv ID 的单篇直下命令，自动分层 TCP → QUIC → browser-hint，
国内 arXiv TCP/443 被重置时也能工作——QUIC/HTTP-3 (UDP) 是逃生通道。

```bash
# 自动传输梯（tcp 快试 → QUIC）— PDF
hfpclawer fetch 2609.02737

# 强制 QUIC；显式输出目录；source 包（TeX 的 gzip tar）
hfpclawer fetch 2608.06013 -k source -t quic --out ~/papers/

# 每次完成都会打印 sha256 — 完整性锚（连同传输审计轨迹存入
# data/download_audit.jsonl）。
# 跨通道校验：同一 ID 抓两次（官方 + 镜像）比对哈希——
# 字节级一致即验证通道可靠。
```

失败语义：中断传输从 `.part` 经 `Range` 续传（新鲜 `.part` 续传；
>24h stale `.part` 回收）；异常一律返回失败结果、永不抛出。
`--kind` 取值: `pdf`（默认）、`source`（TeX 包）、`abs`（摘要页元数据）。

### 其他

```bash
hfpclawer dedup                       # 去重统计
hfpclawer config                      # 查看当前配置
hfpclawer mcp                         # 启动 MCP Server（默认 :8765）

# 数据库操作
hfpclawer paper-stats                 # paper_store 统计
hfpclawer check                       # 完整性检查
hfpclawer wiki                        # Wiki 集成（生成 Wiki 页面）
```

## 配置

### config.yaml

项目根目录 `config.yaml` 是主配置文件，分为 8 个部分：

1. **search** — 搜索源配置、搜索维度、关键词
2. **keywords** — 关键词白名单（高/中/低）+ 黑名单
3. **anti_crawl** — 反爬策略参数
4. **classification** — 分类阈值
5. **hardware** — 硬件资源预算
6. **budget** — Token/费用预算
7. **wiki** — Wiki 集成配置
8. **paths** — 数据/输出路径

### .env

```bash
# API Keys
DEEPSEEK_API_KEY=sk-...
HF_TOKEN=hf_...                      # HuggingFace Token

# 代理
HTTP_PROXY=http://127.0.0.1:7890
HTTPS_PROXY=http://127.0.0.1:7890

# Ollama 本地模型（降级备用）
OLLAMA_API_BASE=http://localhost:11434

# LiteLLM Proxy
LITELLM_PROXY=http://localhost:4000
LITELLM_API_KEY=***
```

## Scrapy 用法

```bash
# 独立模式
scrapy crawl arxiv_search            # arXiv API 搜索
scrapy crawl openreview              # OpenReview 搜索
scrapy crawl hfpapers                # HF Papers 页面爬取
scrapy crawl multi_source            # 多源统一调度

# 分布式模式（需 Redis）
scrapy crawl multi_source -s SETTINGS_MODULE=hfpapers.settings_redis
```

## MCP 远程调用

MCP Server 通过 stdio 协议集成 Hermes Agent / OpenCode：

```bash
# 启动 MCP Server
hfpclawer mcp

# 指定端口
hfpclawer mcp --port 8765 --host 0.0.0.0
```

### 可用工具

| 工具名 | 描述 |
|--------|------|
| `hfpclawer_search` | 搜索新论文 |
| `hfpclawer_download` | 下载 PDF |
| `hfpclawer_convert` | PDF → Markdown |
| `hfpclawer_info` | 查看论文详情 |
| `hfpclawer_list` | 列出已爬取论文 |
| `hfpclawer_stats` | 爬虫统计 |
| `hfpclawer_full` | 全流程 |

## 数据目录

```
hfpapers-crawler/
├── data/           # SQLite DB + JSON 候选列表
│   └── papers.db  # SQLite paper_store
├── pdfs/           # 下载的 PDF
├── mds/            # Markdown 转换结果
├── logs/           # Scrapy 日志
└── md_extracts/    # 备用 MD 提取目录
```
