# hfpclawer — Development Plan (v0.6.x)

master 当前状态：`v0.6.0`（`b1ffef7`，import 原子命令完成）。
本 PLAN 记录当前迭代阶段的具体工作和实现细节。

---

## v0.6.0 — ✅ DONE (2026-06-28)

### 交付

| 文件 | 说明 |
|:-----|:------|
| `hfpclawer/import_paper/resolver.py` | 统一标识符解析 (arXiv/DOI/URL → ResolveResult) |
| `hfpclawer/import_paper/importer.py` | 全流程管线: resolve→dedup→PDF download(3级回退)→convert→store |
| `hfpclawer/import_paper/__init__.py` | 包入口 |
| `hfpapers/cli.py` | `hfpclawer import` 命令 |
| `tests/test_import.py` | 19 tests (all pass) |

### 发现的 Bug
- **arXiv 正则匹配到 DOI**: `\b(\d{4}\.\d{4,5})\b` 不加 `\b` 时 DOI 字符串 `2025.11443` 被错误匹配 → 已修复

---

## v0.6.1 — 搜索超时控制 + PDF 回退链增强 (IN PROGRESS)

### P1-1: 搜索超时控制

**问题：** `hfpclawer search` 的多源分发器可能悬挂 60s+（HF API 限流、OpenReview down 等）。

**方案：**
- 每个 source 加 `concurrent.futures.ThreadPoolExecutor` + 15s timeout
- 首个 source 返回后即用，超时的抛弃（日志记录）
- CLI 暴露 `--search-timeout` 参数（默认 30s）

**文件清单：**
- `hfpapers/sources.py` — 改造 `SearchDispatcher` 为并发搜索
- `hfpapers/cli.py` — 暴露 `--search-timeout` 参数
- `tests/test_sources_timeout.py` — 新增 8 个测试

### P1-2: PDF 下载回退链

**问题：** PDF 下载只有 arXiv PDF 一条路径，arXiv 超时直接失败。

**方案：**
```
arXiv PDF (primary, 已实现)
  → arXiv HTML (fallback, pyquery 提取 + weasyprint 转 PDF)
    → DOI → ... (reserved for Sci-Hub / Unpaywall)
```

**文件清单：**
- `hfpclawer/download/pdf.py` — 新增 PDF 下载器（从 importer.py 抽出）
- `hfpclawer/import_paper/importer.py` — 引用新下载器

### P1-3: 大文件下载

**问题：** 现有 `urllib` 下载对 >10MB PDF（如 JCP 论文～24MB）容易超时。

**方案：** streaming + chunked read + 60s timeout（已在 `_download_pdf` 中部分实现）

---

## v0.6.2 — 开发体验 (NEXT)

### P0-2: Editable Dev Mode 自动化

Makefile target:
```makefile
.PHONY: dev
dev:
	uv pip install -e .
```

### ruff 归零

Fix remaining 13 ruff errors across codebase.

---

## 后续迭代（v0.7.x+）

详见 `ROADMAP.md`。关键路径：
- **v0.7.0**: Formula Registry + L1→L5 (从 gsnv-theory 迁移)
- **v0.7.1**: Citation Network (S2/CrossRef/OpenAlex 3层回退)
- **v0.8.0**: 工程质量 (ruff 归零 + CI)

---

## 已用工具链

| 工具 | 配置 |
|:-----|:------|
| ruff | line-length=100, 双引号, E/W/F/I/N |
| pytest | 含 typeguard + cov 插件 |
| pyright | basic 模式，忽略 torch/scrapy/sentence_transformers 等可选依赖 |
| uv | 虚拟环境 + pip install -e |

---

*本 PLAN 由 Hermes Agent 于 2026-06-28 更新。*
