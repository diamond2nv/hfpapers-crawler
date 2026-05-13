# 开发者指南

## 开发环境

```bash
# 激活 venv
source venv/bin/activate

# 安装开发依赖
pip install -e ".[dev]"

# 代码规范
ruff format .                         # 格式化
ruff check .                          # lint 检查
ruff check . --fix                    # 自动修复

# 类型检查
pyright .                             # 0 errors

# 测试
python -m pytest tests/ -v            # 运行测试
python -m pytest tests/ -x -v         # 失败即停
python -m pytest tests/ -q            # 精简输出
```

## 代码规范

- **语言**: Python 3.10+
- **格式**: Ruff, line-length=100, 双引号
- **类型**: 所有公共函数/方法标注类型
- **日志**: 使用 `logging.getLogger(__name__)`，不 print
- **错误处理**: 日志记录 + 优雅降级，不静默吞异常

## 测试

### 运行测试

```bash
# 所有测试
pytest tests/ -v

# 按模块
pytest tests/test_paper_store.py -v
pytest tests/test_evolved.py -v
pytest tests/test_hardware.py -v
pytest tests/test_sources.py -v
pytest tests/test_config.py -v

# 覆盖报告
pytest tests/ --cov=hfpapers --cov-report=term-missing

# 慢测试
pytest tests/ -v -k "slow"            # 标记为 slow 的测试
pytest tests/ -v -m "not slow"        # 跳过慢测试
```

### 测试策略

1. **单元测试** — 每个模块独立测试，mock 外部依赖
2. **集成测试** — paper_store ↔ SQLite ↔ Crossref（mock 网络）
3. **快照测试** — 配置加载、分类检测边界条件
4. **硬件自适应** — 测试在不同硬件环境下的降级行为

### Fixture

`tests/conftest.py` 提供：

- `test_env` — 自动隔离的临时目录 + 最小 config.yaml
- `paper_store` — 内存 SQLite PaperStore 实例
- `tmp_config` — 可自定义的临时配置
- `mock_hf_cli` — Mock HF CLI 输出

## 项目结构

```
hfpapers-clawler/
├── hfpapers/                    # 主包
│   ├── __init__.py
│   ├── cli.py                   # Typer CLI 入口
│   ├── config.py                # 配置加载 (YAML+env+litellm)
│   ├── evolved.py               # 爬虫核心引擎 + 去重 + 分类 + 下载
│   ├── hardware.py              # 硬件探针 (CPU/GPU/降级)
│   ├── paper_store.py           # SQLite 存储 + 雪花ID + Crossref
│   ├── sources.py               # 多源搜索 (4 种来源)
│   ├── mcp_server.py            # MCP stdio Server
│   ├── items.py                 # Scrapy 数据模型
│   ├── pipelines.py             # Scrapy Pipeline 链
│   ├── middlewares.py           # Scrapy 反爬中间件
│   ├── settings.py              # Scrapy 设置
│   ├── settings_redis.py        # 分布式 Scrapy 设置
│   └── spiders/                 # Scrapy 爬虫
│       ├── hfspider.py          # HF Papers 页面爬虫
│       └── multi_source_spider.py  # 多源统一爬虫
├── tests/                       # 测试目录
│   ├── __init__.py
│   └── conftest.py              # 共享 fixture
├── config.yaml                  # 主配置
├── env.template                 # 环境变量模板
├── scrapy.cfg                   # Scrapy 配置
├── pyproject.toml               # 包配置
├── .gitignore
├── docs/                        # 文档
│   ├── ARCHITECTURE.md
│   ├── USAGE.md
│   └── DEVELOPMENT.md
├── AGENTS.md                    # AI Agent 开发指南
├── data/                        # 数据 (gitignored)
├── pdfs/                        # PDF (gitignored)
├── mds/                         # Markdown (gitignored)
├── logs/                        # 日志 (gitignored)
└── md_extracts/                 # 备用 MD 提取 (gitignored)
```

## 添加新功能

### 添加 CLI 命令

在 `hfpapers/cli.py` 中：

```python
@app.command()
def mycommand(
    param: str = typer.Option("default", "--param", "-p"),
):
    \"\"\"描述\"\"\"
    from hfpapers.module import func
    result = func(param)
    typer.echo(f"结果: {result}")
```

### 添加新的搜索源

1. 在 `hfpapers/sources.py` 中继承 `PaperSource`:
```python
class MySource(PaperSource):
    name = "my_source"
    def search(self, query, category=""):
        ...
```
2. 在 `config.yaml` `search.enabled` 中添加
3. 在 `get_enabled_sources()` 中注册

### 添加 Scrapy Spider

1. 在 `hfpapers/spiders/` 下创建 spider
2. 继承 `scrapy.Spider`，输出 `PaperItem`
3. 在 `settings.py` `SPIDER_MODULES` 中注册
4. 在 `pipelines.py` 中选择性加入 pipeline 链

## 发布

```bash
# 构建
python -m build

# 检查
twine check dist/*

# 发布到 PyPI（如果需要）
twine upload dist/*
```

## 已知问题和限制

1. **PaperWithCode API 已废弃** — `pwc_api` 源可能返回空结果，PwC API 已重定向到 HF API
2. **OpenReview 嵌套字段** — content 字段是嵌套 dict，需要通过 `_safe_field()` 提取
3. **Scrapy 与 paper_store 集成** — spider 直接调用 `ensure_paper()`，绕过 Scrapy pipeline 的 store 阶段
4. **Crossref 速率限制** — 免费 API 50 请求/秒，无需 API key
5. **HF CLI 依赖** — 需要安装 `huggingface_hub` CLI 工具
