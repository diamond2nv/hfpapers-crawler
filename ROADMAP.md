# hfpclawer — Roadmap

hfpclawer 的演进路线图。当前版本 `v0.5.0`（master `4514e7e`），后续所有迭代在 `v0.x.y` 体系内推进，\
`x`（特性版）可到 20，`y`（hotfix）可到 20，不急着冲 v1.0。\
预计在 omega 项目完成后重启开发。

---

## 版本路线

```
v0.5.x ── 稳定维护期
  │
  ├── [DONE] v0.5.0     — 多源搜索 + PDF下载 + SQLite paper_store + MCP server
  ├── [DONE] v0.5.1     — 安全修复(starlette CVE) + docs改进 + NLP infra
  │
  ▼  Ω (omega 开发并行)
  │
v0.6.x ── 已知论文导入专精
  │
  ├── v0.6.0 — hfpclawer import 原子命令（已知ID直给）
  │     ├── --arxiv-id / --doi 参数解析
  │     ├── 查重→下载PDF→转MD→入库 全自动
  │     └── 可选 --to-md 写元数据摘要
  │
  ├── v0.6.1 — 可靠性提升
  │     ├── 搜索超时控制（15s per source, concurrent）
  │     ├── PDF 下载回退链（arXiv → DOI → Sci-Hub）
  │     └── 大文件下载（streaming + resume）
  │
  ├── v0.6.2 — 开发体验
  │     ├── 可编辑安装自动化（Makefile / dev脚本）
  │     └── import 路径的可选元数据字段
  │
  ├── v0.6.3 — v0.6.4 ─ ─ ─ (hotfix / 小改进)
  │     ⋮
  └── v0.6.20
  │
  ▼
v0.7.x ── 知识增强
  │
  ├── v0.7.0 — citations 引用关系表
  │     ├── Semantic Scholar API 引用获取
  │     ├── PDF 引用列表解析
  │     └── hfpclawer store graph 可视化
  │
  ├── v0.7.1 — 元数据增强
  │     └── relevance_meta JSON 字段（得分来源/置信度）
  │
  ├── v0.7.2 — store 变更追踪
  │     └── hfpclawer store diff --since
  │
  ├── v0.7.3 — v0.7.4 ─ ─ ─ (hotfix / 小改进)
  │     ⋮
  └── v0.7.20
  │
  ▼
v0.8.x ── 工程质量
  │
  ├── v0.8.0 — pyproject.toml 版本对齐 check
  ├── v0.8.1 — 关键路径 test coverage
  ├── v0.8.2 — CI/CD 自动化发布
  │
  ├── v0.8.3 — v0.8.4 ─ ─ ─ (hotfix / 小改进)
  │     ⋮
  └── v0.8.20
  │
  ▼
   ⋮
  │
v0.20.x ── 上限特性版
  │
  └── v0.20.0 — v0.20.20
```

> x（特性版）取值范围：6 ～ 20，每个版本内 y（hotfix）取值范围：0 ～ 20。\
> 不设 v1.0 目标，功能积累到成熟自然过渡。

---

## 关键节点

| 版本 | 里程碑 | 预计工作量 |
|------|--------|-----------|
| v0.6.0 | `import` 原子命令 | 2–3 天 |
| v0.6.1 | 可靠性 | 1–2 天 |
| v0.7.0 | citations 图谱 | 3–5 天 |
| 后续 | 按需迭代，不设硬截止 | — |

---

## 不考虑的特性（Deliberate Non-Goals）

- **论文推荐 / 全自动文献综述** — 超出 paper store 范畴，应该由上层 Agent（Hermes）做
- **PDF 内容语义索引** — 向量数据库集成成本高，与 SQLite FTS5 语义检索不兼容
- **云端同步** — paper store 是本地单点数据，同步是文件系统/网盘的事
- **论文笔记/标注** — 属于 wiki 层，不是 store 层

---

## 当前状态摘要（2026-06-08）

| 指标 | 值 |
|------|-----|
| Pypi 版本 | v0.5.0 |
| 最新 commit | 4514e7e（v0.5.0 + starlette CVE fix） |
| Papers in store | 42 篇 |
| 安装方式 | `pip install hfpclawer`（非 editable，落后 git HEAD） |
| 测试 | 91 tests |
| 开发中功能 | 无（omega 期间冻结） |

---

*本 ROADMAP 由 Hermes Agent 于 2026-06-08 生成。omega 开发完成后重启。*
