# hfpclawer — Roadmap

hfpclawer 的演进路线图。当前版本 `v0.6.0`（`b1ffef7`），后续所有迭代在 `v0.x.y` 体系内推进，
`x`（特性版）可到 20，`y`（hotfix）可到 20，不急于冲 v1.0。

---

## 版本路线

```
v0.5.x ── 稳定维护期
  │
  ├── [DONE] v0.5.0     — 多源搜索 + PDF下载 + SQLite paper_store + MCP server
  ├── [DONE] v0.5.1     — 安全修复(starlette CVE) + docs改进 + NLP infra
  │
  ▼  Omega 后重启 (2026-06-28)
  │
v0.6.x ── 已知论文导入专精
  │
  ├── [DONE] v0.6.0     — hfpclawer import 原子命令（已知ID直给）
  │     ├── 统一解析器 (arXiv/DOI/URL → ResolveResult)
  │     ├── 查重→PDF 3级回退下载→pymupdf4llm→PaperStore 全自动
  │     ├── 可选 --title/--abstract/--venue/--skip-pdf/--skip-md
  │     └── 19 tests, ruff 0 errors
  │
  ├── [IN PROGRESS] v0.6.1 — 搜索超时控制 + PDF 回退链增强
  │     ├── 搜索超时控制: 15s per source + concurrent.futures
  │     ├── PDF 下载回退链: arXiv PDF → arXiv HTML → DOI → Sci-Hub
  │     └── 大文件下载 (streaming + chunked + resume)
  │
  ├── v0.6.2 — 开发体验
  │     ├── Makefile dev target (uv pip install -e .)
  │     ├── ruff fix 现有 13 errors → 0
  │     └── import 路径的 --to-md 元数据摘要
  │
  ├── v0.6.3 — v0.6.4 ─ ─ ─ (hotfix / 小改进)
  │     ⋮
  └── v0.6.20
  │
  ▼
v0.7.x ── 公式验证 + 知识增强（融合路线核心）
  │
  ├── v0.7.0 — Formula Registry + L1→L5 验证管线
  │     ├── FormulaRegistry JSONL (从 gsnv-theory 迁移)
  │     ├── L1 SymPy 符号推导
  │     ├── L2 numpy 数值验证
  │     ├── L3 pint 量纲检查
  │     ├── L4 物理极限 / L5 奇异点检测
  │     └── hfpclawer verify <eq-id> 命令
  │
  ├── v0.7.1 — Citation Network 和引文分析
  │     ├── Semantic Scholar API引用获取 (3层回退: S2→CrossRef→OpenAlex)
  │     ├── hfpclawer network build 命令
  │     └── GEXF/GraphML/JSON 导出
  │
  ├── v0.7.2 — 元数据增强
  │     ├── relevance_meta JSON 字段（得分来源/置信度）
  │     ├── citations 引用关系表 (SQL)
  │     └── hfpclawer store diff --since
  │
  ├── v0.7.3 — v0.7.4 ─ ─ ─ (hotfix / 小改进)
  │     ⋮
  └── v0.7.20
  │
  ▼
v0.8.x ── 工程质量
  │
  ├── v0.8.0 — pyproject.toml 版本对齐 check + ruff 归零
  ├── v0.8.1 — 集成测试 + MCP server 测试
  ├── v0.8.2 — 性能测试 (10K store) + 索引优化
  │
  ├── v0.8.3 — v0.8.4 ─ ─ ─ (hotfix / 小改进)
  │     ⋮
  └── v0.8.20
  │
  ▼
v0.9.x ── arXiv 风格可视化
  │
  ├── v0.9.0 — 引文网络 SVG/PDF 渲染 (arXiv 风格)
  ├── v0.9.1 — 词云 + 演化趋势图
  └── v0.9.20
  │
  ▼
   ⋮
  │
v0.20.x ── 上限特性版
  │
  └── v0.20.0 — v0.20.20
```

> x（特性版）取值范围：6 ～ 20，每个版本内 y（hotfix）取值范围：0 ～ 20。
> 不设 v1.0 目标，功能积累到成熟自然过渡。

---

## 关键节点

| 版本 | 里程碑 | 预计工作量 |
|------|--------|-----------|
| v0.6.0 | `import` 原子命令 | ✅ DONE |
| v0.6.1 | 搜索超时 + PDF 回退 | 1–2 天 |
| v0.6.2 | 开发体验 + ruff 归零 | 0.5 天 |
| v0.7.0 | Formula Registry + L1→L5 | 3–5 天 |
| v0.7.1 | Citation Network | 3–5 天 |
| v0.8.0 | 版本对齐 + CI | 1–2 天 |
| 后续 | 按需迭代，不设硬截止 | — |

---

## 架构原则（来源于设计评审 v0.6-design-review.md）

### 验证管线的 2+4 架构
- **独立层（核验层）**: L3 量纲, L5 奇异点（无需 L1 结果）
- **深度层（递进依赖）**: L1 → L2 → L4

### 引用数据源 3 层抽象
- S2Source（主） → CrossRefSrc（备） → OpenAlexSrc（三） → PDFParseSrc（补充）

### 性能边界
| 规模 | PaperStore | FormulaRegistry | CitationGraph |
|------|-----------|-----------------|---------------|
| 100 papers | ✅ 瞬发 | ✅ JSONL | ✅ < 0.1s |
| 1K papers | ✅ 索引 | ⚠️ JSONL 1MB | ✅ < 1s |
| 10K papers | ⚠️ VACUUM | ❌ 需 SQLite | ❌ 需降采样 |

---

## 不考虑的特性（Deliberate Non-Goals）

- **论文推荐 / 全自动文献综述** — 超出 paper store 范畴，应该由上层 Agent（Hermes）做
- **PDF 内容语义索引** — 向量数据库集成成本高，与 SQLite FTS5 语义检索不兼容
- **云端同步** — paper store 是本地单点数据，同步是文件系统/网盘的事
- **论文笔记/标注** — 属于 wiki 层，不是 store 层
- **L6 Lean 4 形式化证明** — 仅预留接口，待社区成熟（500MB+ Mathlib 4）

---

## 当前状态摘要（2026-06-28）

| 指标 | 值 |
|------|-----|
| PyPI 版本 | v0.5.0（本地已 v0.6.0-dev） |
| 最新 commit | `b1ffef7`（v0.6.0 import 命令） |
| 新增模块 | `hfpclawer/import_paper/` (3 files) |
| 安装方式 | `uv pip install -e .`（建议 dev mode） |
| 测试 | 19 新增 + 91 原有 = 110 tests |
| ruff 错误 | 0（新增模块）/ 13（全项目遗留） |
| NAS Forgejo | ✅ My_Hermes_Team/hfpapers-crawler master |
| 设计评审 | `docs/hfpclawer-v06-design-review.md` |

---

*本 ROADMAP 由 Hermes Agent 于 2026-06-28 基于设计评审更新。*
