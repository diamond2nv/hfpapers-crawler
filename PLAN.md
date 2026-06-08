# hfpclawer — Development Plan (Phase 2)

开发阶段说明：当前 master (`v0.5.0-9-g4514e7e`) 为核心功能可用状态。本 PLAN 记录 Phase 2 的功能缺口、技术债务和重构方向，等 omega 开发完成后回来看。

---

## P0 — 当前最痛的功能缺口

### 0.1 `hfpclawer import --arxiv-id` 原子命令

**问题：** 用户/Agent 给定明确 arXiv ID（非关键词搜索）时，hfpclawer 没有直给入口。必须手工 `curl` + `pymupdf4llm` + SQLite 直写，绕过整个工具链。

**设计：**
```
hfpclawer import --arxiv-id 2501.01934 --relevance 88 [--title "..." --to-md --no-download]
```

**执行链（原子操作）：**
1. 查重（`identifiers WHERE id_type='arxiv'`）→ 已存在则 exit
2. 下载 PDF（`https://arxiv.org/pdf/{id}`，Python urllib，60s timeout）
3. pymupdf4llm 转 Markdown（写入 `mds/{arxiv_id}.md`）
4. 写入 `papers` + `identifiers` 表
5. 可选 `--to-md`：同时写一份精简元数据 MD 到 `md_extracts/{arxiv_id}_meta.md`

**依赖：** `pymupdf4llm`（已有 `[pdf]` extra）

### 0.2 Editable Dev Mode 自动化

**问题：** site-packages 里是 pip 安装的 v0.5.0 二进制，与 git HEAD 分离。改代码后要手动 `pip install -e .`（或 `uv pip install -e .`）才生效，开发迭代慢。

**方案A（推荐）：** Makefile target
```makefile
.PHONY: dev
dev:
	uv pip install -e .
```

**方案B：** `.hermes/scripts/hfpclawer-dev.sh`
```bash
#!/bin/bash
cd ~/Documents/Gitlab/Agentic4Sci/hfpapers-crawler
uv pip install -e .
```

---

## P1 — 可靠性与健壮性

### 1.1 搜索超时控制

**问题：** `hfpclawer search` 的多源分发器可能悬挂 60s+（HF API 限流、OpenReview down 等）。

**方案：**
- 每个 source 加 `requests.timeout=15`
- 改用 `concurrent.futures.ThreadPoolExecutor` 并行搜索各 source
- 首个 source 返回后即用，超时的抛弃
- CLI 暴露 `--search-timeout` 参数（默认 30s）

### 1.2 Semantic Scholar / arXiv API 回退链

**问题：** 下载 PDF 目前只有 arXiv 一条路径。arXiv timed out 直接失败。

**方案：**
```
arXiv PDF (primary)
  → arXiv HTML (fallback, 用 pyquery 提取)
    → DOI → Sci-Hub (可选 fallback)
```

### 1.3 PDF 大文件下载

**问题：** `curl -sL -o` 默认 30s timeout，对 >10MB PDF（如 JCP 论文～24MB）容易超时。

**方案：** 已用 Python `urllib` + `ssl._create_unverified_context()` + 60s timeout 解决。封装成 `downloader.py` 的下层函数。

---

## P2 — 功能增强

### 2.1 relevance 元数据字段

**问题：** `relevance` 只有 int rank，没有置信度、来源说明、时间戳。

**方案：** 新增列 `relevance_meta TEXT`，存 JSON：
```json
{"method": "keyword_match", "score": 0.88, "source": "abstract", "updated_at": "2026-06-08"}
```

### 2.2 citations 引用关系表

**问题：** paper store 是扁平列表，文献综述需要"谁引了谁"的知识图谱。

**方案：** 新增表：
```sql
CREATE TABLE citations (
    citing_sf_id TEXT NOT NULL,
    cited_sf_id TEXT NOT NULL,
    context TEXT,           -- "参见 Section 3.2"
    source TEXT,            -- "semantic_scholar" | "pdf_extract"
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (citing_sf_id, cited_sf_id),
    FOREIGN KEY (citing_sf_id) REFERENCES papers(sf_id),
    FOREIGN KEY (cited_sf_id) REFERENCES papers(sf_id)
);
```

**填充策略：**
- v1: Semantic Scholar API 拉取（`/paper/arXiv:ID/references`）
- v2: PDF 引用列表解析（pymupdf4llm + regex DOI/arXiv 提取）

### 2.3 `hfpclawer store diff` — store 变更记录

**问题：** 没有清晰的变更日志，不知道某次操作新增/更新了哪些论文。

**方案：** `hfpclawer store diff --since YYYY-MM-DD` 输出时间段内的新增/更新记录。

### 2.4 多标识符查询强化

**问题：** 目前通过 DOI/arXiv/URL 查重走 `identifiers` 表。但没有统一的"解析输入→找论文"入口。

**方案：** 统一解析器 `resolve_identifier(input: str) -> sf_id`
- `2501.01934` → arxiv
- `10.1016/j.jcp.2025.114432` → doi
- `https://arxiv.org/abs/2501.01934` → URL → arxiv 提取

---

## P3 — 工程质量

### 3.1 pyproject.toml 对齐

**问题：** 版本号通过 `importlib.metadata` 动态获取，在 site-packages 里回退到 `"0.0.0"`。`pyproject.toml` 里的 `version` 字段与 git tag 没有强制对齐。

**方案：** 发布前 CI check 脚本验证 `pyproject.toml version == git tag`。

### 3.2 test coverage 不足

**问题：** 目前 91 个 test，覆盖 SQLite 读写和搜索 mock。但 PDF 下载链路、pymupdf4llm 转换、MCP server 等路径无 test。

**方案：** 逐步补，以 PDF 下载/转换为 P0。

---

## 开发顺序建议

```
Phase 2.0 (当前优先级最高)
  ├── P0-1: hfpclawer import --arxiv-id
  └── P0-2: editable dev mode

Phase 2.1 (核心完善)
  ├── P1-1: 搜索超时控制
  ├── P1-2: PDF 下载回退链
  └── P1-3: 大文件下载

Phase 2.2 (知识增强)
  ├── P2-2: citations 引用表
  └── P2-1: relevance_meta

Phase 2.3 (质量)
  ├── P3-1: pyproject 对齐
  └── P3-2: test coverage
```

---

*本 PLAN 由 Hermes Agent 于 2026-06-08 基于实际使用体验生成。在 omega 开发完成后复审。*
