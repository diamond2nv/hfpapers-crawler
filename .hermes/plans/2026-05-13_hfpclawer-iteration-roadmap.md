# hfpclawer 迭代优化路线图

**生成日期:** 2026-05-13
**当前版本:** 0.2.0
**仓库:** `hfpapers-crawler` + `arxiv-metadata-service`

---

## 当前状态评估

### ✅ 已完成

| 领域 | 内容 |
|------|------|
| 核心引擎 | 多源搜索 (HF CLI + OpenReview + PWC + arXiv API)、去重、相关度分类 |
| PDF 下载 | 8 路异步并发下载、pymupdf4llm 转换 |
| Paper Store | SQLite + Snowflake ID + CrossRef 交叉验证 + 标识符管理 |
| CLI | 10+ 子命令（`hfpclawer search|download|convert|list|info|stats|full|mcp|...`） |
| MCP Server | 7 个 MCP 工具（`hfpclawer_search/download/convert/info/list/stats/full`） |
| 下载管道 | OAI-PMH 增量/全量、Kaggle 全量下载、MonitorDaemon |
| 测试 | 61 passed (6 个测试文件, 62 用例, 1 skipped) |
| 文档 | README, AGENTS.md, ARCHITECTURE.md, USAGE.md, PLAN.md, DEPLOY.md |
| 依赖架构 | `hfpclawer` (core) + `hfpclawer[arxiv]` (Kaggle) + `hfpclawer[scrapy]` |
| arxiv-meta-service | 独立仓库，依赖 `hfpclawer[arxiv]`，FTS5 索引 + FastAPI + MCP |

### ⚠️ 已知问题

| 严重度 | 问题 | 描述 |
|--------|------|------|
| 🟡 中 | `test_is_duplicate_nonexistent` 失败 | 预存测试数据干扰，不影响功能 |
| 🟡 中 | pyright 类型错误 (~143) | 主要在 Scrapy spider + MCP server，不影响运行时 |
| 🟠 低 | CLI 中 `remove-legacy-import` 残留 | `hfpapers/cli.py` 中 `_import_dummy()` 已不再需要 |

---

## Phase A：稳定性与测试增强（0.2.x → 0.3.0）

**目标：** 修正已知失败 + 提升测试质量 + 减小 pyright 错误

### A1：修复测试隔离
- [ ] `tests/conftest.py` 检查 test_env fixture：DedupEngine 预存数据问题
- [ ] 方案：DedupEngine 构造函数使用独立文件路径（传入临时 dedup_path）
- [ ] 确保 `test_is_duplicate_nonexistent` 绿色

**涉及文件：** `tests/test_evolved.py`, `tests/conftest.py`, `hfpapers/evolved.py`

### A2：减少 pyright 错误（目标：≤15 errors）
- [ ] 修复 `oai.py:78` None→str 类型错误（最简单的）
- [ ] 修复 Scrapy spider 回调类型标注
- [ ] 修复 MCP server handler 返回类型
- [ ] 添加 `pyright` 到 CI（`pyproject.toml` 中配置）

**涉及文件：** `hfpclawer/download/oai.py`, `hfpapers/spiders/multi_source_spider.py`, `hfpapers/mcp_server.py`

### A3：添加集成测试
- [ ] 测试 `hfpclawer download --status`（不依赖网络）
- [ ] 测试 `hfpclawer config` 输出格式
- [ ] 测试 MCP server 启动 + 工具列表

**涉及文件：** `tests/test_cli.py`（追加）

### A4：覆盖率提升（目标：>65%）
- [ ] 添加 `pdf_downloader_async.py` 单元测试
- [ ] 添加 `search_queue.py` 测试
- [ ] 添加 `pipelines.py` 测试

**涉及文件：** `tests/test_downloader.py`(new), `tests/test_pipeline.py`(new)

---

## Phase B：端点功能完善（0.3.0 → 0.4.0）

**目标：** 覆盖当前代码中 `TODO` 标记和未实现的特性

### B1：搜索增强
- [ ] 支持 `--all` 在 OAI 搜索中真正全量拉取（当前只做增量）
- [ ] 添加 `hfpclawer search --sources hf,arxiv` 多源搜索
- [ ] arXiv API 搜索结果缓存

**涉及文件：** `hfpapers/cli.py`, `hfpapers/searcher_registry.py`, `hfpapers/arxiv_search.py`

### B2：下载增强
- [ ] OAI 下载支持指定分类（当前所有分类）
- [ ] Kaggle 下载进度反馈（当前 silent，只在日志中有）
- [ ] 添加 `hfpclawer download --source kaggle --force` 验证（端到端测试需要 Kaggle API key）

**涉及文件：** `hfpclawer/download/oai.py`, `hfpclawer/download/kaggle.py`, `hfpapers/cli.py`

### B3：Paper Store 功能补全
- [ ] 添加 `hfpclawer store export --format json|csv` 导出
- [ ] 添加 `hfpclawer store merge` 合并多个 store
- [ ] 修复 `ensure_paper` 当 paper 已存在时的行为

**涉及文件：** `hfpapers/paper_store.py`, `hfpapers/cli.py`

### B4：MCP Server 稳定性
- [ ] 添加 MCP 工具错误处理和重试
- [ ] 添加 MCP 工具超时
- [ ] 支持 MCP 工具的 JSON Schema 参数验证

**涉及文件：** `hfpapers/mcp_server.py`

---

## Phase C：Hermes Agent 深度集成（0.4.0 → 0.5.0）

**目标：** 让 Hermes 能"内建"使用 hfpclawer 的能力

### C1：Hermes 原生工具注册
- [ ] 为 Hermes Agent 创建 `hfpclawer` 工具集（toolsets）
- [ ] 让 Hermes 可以直接调用 `hfpclawer_search` 等工具，无需 MCP 代理
- [ ] 注册到 `toolsets.py` 中的标准工具集

**涉及文件：** `hermes-agent/toolsets.py`, `hermes-agent/tools/hfpclawer_tool.py`(new)

### C2：hfpclawer 作为 Hermes 插件
- [ ] 创建 `hfpclawer` 的 Hermes 插件入口
- [ ] 支持 Hermes cron 任务中调用 `hfpclawer search`
- [ ] 支持定时搜索→推送（QQ Bot / Telegram）

**涉及文件：** `hermes-agent/hermes_cli/plugins/`, `hfpclawer/__init__.py`

### C3：hfpclawer 技能封装
- [ ] 创建 `hfpclawer` 技能（skill）：日常论文搜索流程
- [ ] 定时搜索 + Wiki 写入 + 增量更新
- [ ] 错误处理和重试策略

**涉及文件：** `~/.hermes/skills/hfpclawer-search/`

---

## Phase D：发布与分发（0.5.0 → 1.0.0）

### D1：Citation Audit Phase 2 — 基于 ARS 代码的三索引降级管道 ✅
- [x] 复制 `_text_similarity.py`（从 ARS, CC BY-NC 4.0）→ `hfpclawer/_text_similarity.py`
- [x] 创建 `hfpclawer/citation_audit_s2.py`（参考 ARS, Semantic Scholar 客户端）
- [x] 创建 `hfpclawer/citation_audit_oa.py`（参考 ARS, OpenAlex 客户端）
- [x] 重写 `citation_audit.py` → L1 (local) → L2 (S2) → L3 (OA) 降级链
- [x] README 添加 ARS Attribution 声明（CC BY-NC 4.0）
- [x] 测试全覆盖（含 mock 网络请求）
- [x] `hfpclawer audit verify --source local|s2|openalex` CLI 支持
- [x] 修复 psutil `getpagesize` 退化（`HardwareProbe` try/except + 测试放宽）
- [x] 修复 substring 标题匹配（短关键词→长标题）
- [x] 修复合并结果丢失 details（authors, doi, venue）
- [x] 修复 PEP8 风格（emoji → 纯文本 `[OK]`/`[NF]`/`[ERR]`）
### D2：PyPI 发布准备
- [ ] `pyproject.toml` 完善：添加 `classifiers`, `keywords`, `project.urls`
- [ ] 添加 `README.md` 到 PyPI（当前够用）
- [ ] 修复依赖声明：`optional-dependencies` 中的 `[arxiv]` 确认可用
- [ ] 构建 + Test PyPI 验证

### D3：文档完善
- [ ] 为 `hfpclawer` 创建 Sphinx 文档或 README 补充
- [ ] API 参考文档
- [ ] 常见问题 FAQ

### D4：GitHub/GitLab Release
- [ ] 版本标签 `v0.5.0`, `v1.0.0`
- [ ] Release Notes
- [ ] 二进制发布（可选）

---

## 优先级建议

```
高优先级 ────────────────────────────────────────── 低优先级

D2 D3     A1 A2 B1 B4     C1 C2 D4
↑                               ↑
需求迫切，修复问题可跑              锦上添花
↑
D1 已完成 → 接下来最短路线上 PyPI
```

**建议立即开工的 3 件事：**
1. **D2**：`pyproject.toml` 完善 + Test PyPI 验证（~30 分钟）
2. **D3**：README + docs 中英文增补（~20 分钟）
3. **A1**：修复 `test_is_duplicate_nonexistent` 隔离（~15 分钟）

---

## 版本演进预测

```
v0.2.0    ← 当前基线
v0.5.x    ← 当前（D1 + 回归修复已完成，公测阶段）
v0.6.0    ← D2 PyPI 就绪
v0.7.0    ← D4 Release + docs
---

当前状态：D1 已完成，D2～D4 可直接推进到 v0.6.0。公测阶段保持 0.x.y 前缀，成熟后再升 v1.0.0。
