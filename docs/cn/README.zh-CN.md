<p align="center">
  <a href="../../README.md">English</a> | <a href="README.zh-CN.md">简体中文</a>
</p>

# hfpapers-clawler — 多源学术论文爪取工具

> **命名哲学**: `claw`（利爪）≠ `crawl`（爬行）。
> `hfpclawer` = HF (HuggingFace Papers) + claw (爪) + er (者)
> = "用利爪精准抓取论文的智能工具"
>
> 不是 crawler（网络爬虫），而是比爬虫更快、更准、更猛的 **爪取者** 🦞

多源学术论文爪取器，专为 PDE / 神经算子 / 物理信息机器学习领域设计。
内置 SQLite Paper Store、Crossref 交叉验证、反爬 Scrapy 管道和 MCP 服务器。

---

## 快速开始

```bash
# 安装
pip install hfpclawer

# 初始化配置
hfpclawer init --quick

# 编辑 .env 填入 API Key
cp .env.template .env

# 开始搜索
hfpclawer search
```

### 可选依赖

| 功能 | 安装命令 | 用途 |
|------|----------|------|
| LLM 分析 | `pip install hfpclawer[llm]` | `sniff` / `analyze` 命令 |
| PDF 转换 | `pip install hfpclawer[pdf]` | PDF → Markdown |
| Scrapy 爬虫 | `pip install hfpclawer[scrapy]` | 多源爬虫 |
| arXiv 本地搜索 | `pip install hfpclawer[arxiv]` | 仅声明依赖命名空间（PyPI 不支持 `git+https`）。需手动 `git clone` 后安装，详见 [Kaggle 元数据指南](kaggle-metadata.zh-CN.md) |
| 引用核验 | `pip install hfpclawer[audit]` | 引用真实性与声明验证（见 [citation_audit](../USAGE.md#citation-audit)） |
| 开发工具 | `pip install hfpclawer[dev]` | 测试、lint |

### 本地开发

```bash
git clone <your-repo>
cd hfpapers-crawler
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
hfpclawer --help
```

### 配置

首次使用运行 `hfpclawer init`，生成 `config.yaml` 和 `.env.template`。
然后编辑 `config.yaml` 调整搜索关键词和数据路径。

---

## CLI 命令

```bash
# 搜索论文
hfpclawer search                    # 默认搜索，显示新论文
hfpclawer search --max-pages 5      # 搜索更多页
hfpclawer search --dry-run          # 仅显示，不保存

# 完整流程：搜索 → 下载 → 转换
hfpclawer full

# Paper Store（SQLite 论文存储）
hfpclawer store stats               # 存储统计
hfpclawer store search              # 列出所有论文
hfpclawer store search --keyword "FNO"

# 下载与转换
hfpclawer download                  # 下载前 20 篇 PDF
hfpclawer convert                   # PDF → Markdown

# MCP Server（用于 Hermes Agent / OpenCode 集成）
hfpclawer mcp                       # 默认端口 :8765

# 初始化配置
hfpclawer init --quick               # 快速生成配置文件
```

---

## Python API

```python
from hfpapers.paper_store import PaperStore, PaperRecord, ensure_paper

# 创建存储
store = PaperStore(db_path="/tmp/papers.db")

# 添加论文
rec = PaperRecord(
    title="Fourier Neural Operator",
    abstract="Learning PDE solution operators with Fourier transforms",
    year=2023,
    source="my_app",
    relevance=90,
)
sf_id = store.upsert_paper(rec)
store.add_identifier(sf_id, "arxiv", "2010.08895")

# 搜索
papers = store.search_papers("neural operator")
for p in papers:
    print(f"[{p.relevance}] {p.title}")

# 硬件探测
from hfpapers.hardware import HardwareProbe
hw = HardwareProbe()
print(f"Hardware: {hw.summary()}")
```

---

## MCP 服务器

hfpapers-crawler 内置 MCP 服务器，用于 AI Agent 集成：

```bash
hfpclawer mcp
```

在 Hermes Agent `~/.hermes/config.yaml` 中注册：

```yaml
mcp:
  servers:
    hfpapers:
      command: "hfpclawer"
      args: ["mcp", "--port", "8765"]
```

可用 MCP 工具：`hfpclawer_search`, `hfpclawer_download`, `hfpclawer_convert`, `hfpclawer_info`, `hfpclawer_list`, `hfpclawer_stats`, `hfpclawer_full`。

---

## 架构

```
┌─ CLI (Typer) ─┐  ┌─ MCP Server ─┐
└──────┬────────┘  └──────┬───────┘
       └────────┬──────────┘
                ▼
┌─ Scrapy Layer (多源) ──────────────────┐
│  ArxivSearchSpider | OpenReviewSpider   │
│  HFPapersSpider | MultiSourceSpider     │
│  中间件: UA随机, 延迟, 代理...          │
│  管道: 存储→分类→导出→下载              │
└──────────────────┬──────────────────────┘
                   ▼
┌─ Paper Store (SQLite) ─────────────────┐
│  papers (雪花ID) | identifiers         │
│  crossref_cache | CrossrefClient       │
└────────────────────────────────────────┘
```

---

## 测试

```bash
pip install -e ".[dev]"
pytest tests/ -v              # 运行所有测试
pytest tests/ --cov=hfpapers  # 含覆盖率
```

---

## 许可证

MIT

## Hermes Agent 技能

以下技能可在 **Hermes Agent**（或任何支持 Hermes 技能格式的 AI 助手）中自动化常见 hfpclawer 工作流：

| 技能 | 用途 | 安装 |
|:-----|:------|:------|
| `hfpclawer-paper-search` | 自动搜寻论文 → 下载 → 转换 → wiki 同步 | `hermes skills install https://raw.githubusercontent.com/diamond2nv/hfpapers-crawler/main/skills/hfpclawer-paper-search/SKILL.md` |
| `hfpclawer-citation-audit` | 通过 S2 + OpenAlex 验证引用 | `hermes skills install https://raw.githubusercontent.com/diamond2nv/hfpapers-crawler/main/skills/hfpclawer-citation-audit/SKILL.md` |

安装后，在任何 Hermes 对话中用 `skill_view(name='hfpclawer-paper-search')` 加载。

## 致谢

本项目包含改编自以下项目的代码：

- **academic-research-skills** by Cheng-I Wu
  (https://github.com/Imbad0202/academic-research-skills)
  - `hfpclawer/_text_similarity.py` — 标题标准化与相似度评分
  - `hfpclawer/citation_audit_s2.py` — Semantic Scholar API 客户端（架构参考）
  - `hfpclawer/citation_audit_oa.py` — OpenAlex API 客户端（架构参考）
  基于 CC BY-NC 4.0 (https://creativecommons.org/licenses/by-nc/4.0/) 许可

## 链接

- [使用指南](USAGE.zh-CN.md)
- [架构文档](ARCHITECTURE.zh-CN.md)
- [开发者指南](DEVELOPMENT.zh-CN.md)
- [Paper Store 参考](paper_store.zh-CN.md)
- [分布式部署指南](../DISTRIBUTED.md)
- [Docker 部署指南](../DOCKER.md)
