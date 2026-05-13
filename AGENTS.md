# hfpapers-clawler — AI Agent 开发指南

此文件适用于 AI 编码助手（Hermes Agent、OpenCode、Claude Code 等）在该项目上工作时读取。
提供了项目结构、关键模式、坑点和约束。

## 快速导航

```
~/Gitlab/Agentic4Sci/hfpapers-clawler/
├── hfpapers/             # 主 Python 包
├── tests/                # pytest 测试
├── docs/                 # 文档
├── config.yaml           # 主配置（YAML + .env 覆盖）
├── pyproject.toml        # 包配置（setuptools）
├── AGENTS.md             # ← 本文档
└── .gitignore
```

## 核心架构约定

### 3 层存储

| 层 | 位置 | 用途 | 持久性 |
|----|------|------|--------|
| SQLite | `data/papers.db` | 主存储 (3 表) | 持久 |
| JSON | `data/candidates_latest.json` | 快速查询缓存 | 覆盖写 |
| 文件 | `pdfs/` `mds/` | 下载结果 | 持久 |

### 关键数据流

```
HF CLI → arXiv验证 → 关键词分类 → Dedup → paper_store (SQLite)
                                                      ↓
                                              PDF下载 → MD转换
```

### 模块依赖链

```
sources.py       — 多源搜索 (HF/OpenReview/PwC/arXiv)
       ↓
paper_store.py   — SQLite 存储 (Snowflake + Crossref)
       ↓
evolved.py       — 爬虫引擎 (HFPapersCrawler / DedupEngine / PaperDownloader)
       ↓
cli.py           — Typer CLI (10+ 子命令)
mcp_server.py    — MCP Server (7 工具)
```

### 配置加载

```python
from hfpapers.config import load_config, get

cfg = load_config()        # 加载 YAML + .env
val = get("search.queries")  # 点号分隔访问
```

配置搜索顺序: `config.yaml` → `.env` (只覆盖 API keys)

### 全局单例

`paper_store.py` 暴露高层接口:

```python
from hfpapers.paper_store import get_store, get_crossref, ensure_paper, store_stats

store = get_store()        # PaperStore 单例
cr = get_crossref()        # CrossrefClient 单例
sf_id, is_new = ensure_paper(arxiv_id, title, ...)  # 写入+去重+交叉验证
stats = store_stats()      # 统计信息
```

## 开发命令

```bash
source venv/bin/activate    # 必须激活
ruff format .               # 格式化 (line-length=100, 双引号)
ruff check .                # Lint
pyright .                   # 类型检查 (0 errors)
python -m pytest tests/ -v  # 测试
python -m build             # 构建包
```

## 测试规范

### 项目指定fixture

`tests/conftest.py` 提供:
- `test_env` — 自动隔离的临时目录 + 最小 config.yaml
- `paper_store` — 内存 SQLite PaperStore 实例

### 测试策略

| 类别 | 覆盖内容 | 外部依赖 |
|------|---------|---------|
| Unit | paper_store CRUD、Snowflake、config | 无 |
| Unit | DedupEngine、RelevanceDetector | 无 |
| Unit | HardwareProbe | psutil |
| Integration | paper_store ↔ SQLite | SQLite |
| Integration | sources 搜索 | Mock |

创建新测试:
1. `tests/test_<module>.py`
2. 使用 `test_env` fixture 隔离环境
3. Mock 网络请求 (requests / subprocess)
4. 不要依赖外部 API 响应

## 坑点

### paper_store.py 导入 circular

`paper_store.py` 中的 `CrossrefClient.cross_verify()` 导入 `HFPapersCrawler._title_similarity`:

```python
from hfpapers.evolved import HFPapersCrawler  # 函数内 import，避免 circular
```

不要把这行提到模块顶部。

### 临时目录隔离

测试 fixture `test_env` 已 chdir 到临时目录。不要硬编码 `~/.hermes/` 或其他系统路径。

### Scrapy 与 CLI 冲突

Scrapy 的 `pipelines.py` 直接调用 `ensure_paper()`，如果 spider 没设 `sf_id`, `StorePipeline` 会跳过。检查 `pipelines.py` 第 38-69 行。

### PwC API 已废弃

PapersWithCode API 已重定向到 HuggingFace API。`sources.py` 中的 `PwcApiSource` 可能返回空结果。

### 硬件自适应

```python
probe = HardwareProbe()
if probe.use_pdf_converter:   # 检查 pymupdf4llm 是否可用
    ...
if probe.use_bert:            # 检查 CUDA + sentence-transformers
    ...
```

## 文件操作

- ❌ 不要用 `cat`/`grep`/`sed`/`ls` — 用 `read_file`/`search_files`/`patch`
- ✅ 用 `write_file` 写文件，`terminal` 跑命令
- ✅ 用 `search_files(target="files")` 代替 `ls`
- ✅ 用 `search_files(pattern="content")` 代替 `grep`

## Git 规范

```bash
git add <files>
git commit -m "<type>: <description>"
git tag v3.1.0          # 语义化版本
```

`.gitignore` 已排除: `*.db`, `data/`, `pdfs/`, `mds/`, `logs/`, `__pycache__/`, `*.egg-info/`, `venv/`, `.ruff_cache/`

## 版本规范

**当前版本: 0.2.0**（未发布，预发布阶段）
- 全部使用 0.x.y 语义版本号，x=大功能迭代，y=修复/小改
- 正式发布前不升到 1.0.0
- 版本号统一在 `hfpapers/__init__.py` 的 `__version__` 中定义
- `pyproject.toml` 中的 version 字段同步更新
- 发版时: `git tag v0.x.y && git push --tags`

## 命名规范

本项目的命名体系基于英文词源学，两个核心词有截然不同的含义：

### claw ≠ crawl（两个独立词，非笔误）

| 词 | 音标 | 含义 | 语境 |
|----|------|------|------|
| **claw** | /klɔː/ | n. 爪/钳；v. 用爪子攫取 | 动物利爪、机械爪、猛禽抓取 |
| **crawl** | /krɔːl/ | v. 爬行，匍匐前进 | 网络爬虫（spider/crawler）|

来源：https://cn.bing.com/dict/search?q=claw

### 包名 hfpclawer 的命名哲学

```
hfpclawer = HF (HuggingFace Papers) + claw (爪) + er (者)
         = "用利爪精准抓取 HF 论文的智能工具"
         ≠ crawler（网络爬虫）
```

- **claw**（利爪）比 **crawl**（爬行）更有攻击性和精准度
- 寓意：不是慢吞吞的爬虫，而是像猛禽用爪攫取猎物的高效抓取工具
- 创造词 `clawler` = `claw` + `-er`（执行者后缀）
- 与热门词 **OpenClaw**（开源爪取工具）呼应，符合销售推广策略

### 项目中两种角色的区分

| 名称 | 类型 | 语义 | 是否修改 |
|------|------|------|----------|
| `hfpclawer` | PyPI 包名、CLI 命令名 | claw（爪取者） | ✅ 正确的名字，保留 |
| `hfpapers-clawler` | GitLab 仓库名 | claw（爪取者） | ✅ 正确的名字，保留 |
| `hfpclawer[arxiv]` | 可选依赖 | 含 Kaggle 全量元数据下载 | ✅ 推荐用法 |
| `HFPapersCrawler` | Python 类名（evolved.py） | crawl（网络爬虫引擎） | ✅ 名实相符，保留 |
| `HFPCrawler/1.0` | HTTP User-Agent | crawl（爬虫标识） | ✅ 符合 HTTP 语义，保留 |

**关键区分：** 包名/仓库名的 `clawler` 不是笔误，是与 `HFPapersCrawler` 类完全不同的词源。
