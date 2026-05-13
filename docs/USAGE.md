# hfpapers-clawler 使用指南

## 安装

```bash
# 克隆项目
cd ~/Gitlab/Agentic4Sci/hfpapers-clawler

# 创建虚拟环境（Python >= 3.10）
python -m venv venv
source venv/bin/activate

# 安装依赖
pip install -e .          # 基础安装
pip install -e ".[scrapy]"  # 含 Scrapy（需额外依赖）
pip install -e ".[dev]"     # 含开发工具

# 配置
cp env.template .env
# 编辑 .env 填入 API keys

# 验证
hfpclawer --help
```

## CLI 命令

`hfpclawer` 提供 10+ 子命令：

### 搜索与爬取

```bash
# 搜索新论文（HF CLI → arXiv验证 → 关键词分类）
hfpclawer search                     # 默认 3 页，阈值 30
hfpclawer search --max-pages 5       # 搜索更多
hfpclawer search --threshold 50      # 更高相关度阈值
hfpclawer search --dry-run           # 仅显示，不保存

# 完整流程：search → download → convert
hfpclawer full

# 多源搜索（配置驱动）
hfpclawer crawl
```

### 存储管理

```bash
# SQLite Paper Store 操作
hfpclawer store stats                # 存储统计
hfpclawer store search --keyword "FNO"  # 搜索论文
hfpclawer store search               # 列出所有论文
hfpclawer store ensure --aid 2301.11167 --title "..."  # 确保论文存在
hfpclawer store verify --aid 2301.11167 --title "..."  # CrossRef 交叉验证
hfpclawer store ids --aid 2301.11167  # 查论文所有标识符
```

### 下载与转换

```bash
# 下载候选论文 PDF
hfpclawer download                    # 下载 TOP-20
hfpclawer download --limit 50         # 下载更多

# PDF → Markdown 转换
hfpclawer convert                     # pymupdf4llm 批量转换

# 查看论文列表
hfpclawer list                        # 列出已爬取论文
hfpclawer info 2301.11167             # 单篇论文详情
```

### 其他

```bash
hfpclawer dedup                       # 去重统计
hfpclawer config                      # 查看当前配置
hfpclawer mcp                         # 启动 MCP Server (默认 :8765)

# 数据库操作
hfpclawer paper-stats                 # paper_store 统计
hfpclawer check                       # 完整性检查
hfpclawer wiki                        # Wiki 集成（生成 wiki 页面）
```

## 配置

### config.yaml

项目根目录 `config.yaml` 是主配置，分为 8 个部分：

1. **search** — 搜索源配置、搜索维度、关键词
2. **keywords** — 关键词白名单 (high/medium/low) + 黑名单
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
LITELLM_API_KEY=sk-...
```

## Scrapy 使用

```bash
# 单机模式
scrapy crawl arxiv_search            # arXiv API 搜索
scrapy crawl openreview              # OpenReview 搜索
scrapy crawl hfpapers                # HF Papers 页面爬取
scrapy crawl multi_source            # 多源统一调度

# 分布式模式（需要 Redis）
scrapy crawl multi_source -s SETTINGS_MODULE=hfpapers.settings_redis
```

## MCP 远程调用

MCP Server 通过 stdio 协议与 Hermes Agent / OpenCode 集成：

```bash
# 启动 MCP Server
hfpclawer mcp

# 或指定端口
hfpclawer mcp --port 8765 --host 0.0.0.0
```

### 可用工具

| 工具名称 | 描述 |
|----------|------|
| `hfpclawer_search` | 搜索新论文 |
| `hfpclawer_download` | 下载 PDF |
| `hfpclawer_convert` | PDF → Markdown |
| `hfpclawer_info` | 查论文详情 |
| `hfpclawer_list` | 列出已爬取论文 |
| `hfpclawer_stats` | 爬虫统计 |
| `hfpclawer_full` | 全流程 pipeline |

## 数据目录

```
hfpapers-clawler/
├── data/           # SQLite DB + JSON 候选列表
│   └── papers.db  # SQLite paper_store
├── pdfs/           # 已下载 PDF
├── mds/            # Markdown 转换结果
├── logs/           # Scrapy 日志
└── md_extracts/    # 备用 MD 提取目录
```
