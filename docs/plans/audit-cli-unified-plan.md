# `hfpclawer audit` — 引用溯源统一引擎设计

> **目标**: 将 coc-inverse-agent 的 `citation_traceability.py` (438 行) 与 hfpclawer 现有的 `citation_audit.py` (525 行) 抽象合并为 `hfpclawer audit` CLI 子命令。

## 一、现状分析

### 现有能力矩阵

| 能力 | coc 的 citation_traceability | hfpclawer 的 citation_audit | 合并后 |
|:-----|:---------------------------|:---------------------------|:------|
| 🅰 BibTeX 解析 & 元数据验证 | ✅ arXiv API 模糊标题匹配 | ❌ — | ✅ 统一 |
| 🅱 DOI 元数据验证 | ✅ DOI.org CSL JSON | ❌ — | ✅ 统一 |
| 🅲 跨库交叉验证 | ✅ coc refs.jsonl × fusion arxiv-all.jsonl | ❌ — | ✅ |
| 🅳 Notebook 引用提取 | ✅ .ipynb → arXiv ID / DOI | ❌ — | ✅ |
| 🅴 L1 本地 SQLite 存在性 | ❌ — | ✅ | ✅ |
| 🅵 L2 Semantic Scholar API | ❌ — | ✅ | ✅ |
| 🅶 L3 OpenAlex API | ❌ — | ✅ | ✅ |
| 🅷 文本相似度置信度评分 | ❌ 硬匹配 | ✅ 0.70 阈值 | ✅ 统一 |
| 🅸 批量审计 JSON 报告 | ✅ | ✅ | ✅ 统一格式 |
| 🅹 CLI 入口 | ❌ 独立脚本 | ❌ 无 CLI 集成 | ✅ `hfpclawer audit` |
| 🅺 跨仓库部署 (coc/fusion) | ✅ 自动探测 | ❌ — | ✅ |

### 代码现状

```
hfpclawer/
├── audit.py                  — 数据源审计 (download stats)
├── citation_audit.py         — 525 行, L1/L2/L3 引用验证
├── citation_audit_oa.py      — OpenAlex 审计
├── citation_audit_s2.py      — Semantic Scholar 审计
```

```
coc-inverse-agent/
├── src/coc/references/verify.py   — 468 行, 元数据验证
├── scripts/citation_traceability.py  — 438 行, 溯源引擎
```

## 二、架构设计

### 模块结构

```
hfpclawer/
├── audit/
│   ├── __init__.py            — 导出 run_audit(), cli()
│   ├── bib.py                 — BibTeX 解析 + arXiv/DOI 元数据验证 (← coc verify.py)
│   ├── store.py               — JSONL 跨库加载 + 匹配 (← coc 重构)
│   ├── notebook.py            — .ipynb 引用提取 (← coc)
│   ├── l1_local.py            — L1: SQLite 存在性检查 (← citation_audit.py)
│   ├── l2_semantic_scholar.py — L2: S2 API (← citation_audit_s2.py)
│   ├── l3_openalex.py         — L3: OpenAlex API (← citation_audit_oa.py)
│   ├── similarity.py          — 文本相似度 & 标题标准化 (← _text_similarity.py)
│   ├── report.py              — 报告生成 (JSON + 摘要)
│   └── traceability.py        — 跨仓库溯源引擎 (整合所有层)
├── citation_audit.py          → 废弃, 移入 audit/
├── citation_audit_oa.py       → 废弃
├── citation_audit_s2.py       → 废弃
```

### CLI 树

```
hfpclawer audit --help

  Usage: hfpclawer audit [OPTIONS] COMMAND [ARGS]...

  ┌─ audit bib ───────────────────────────────────────────────
  │  解析 references.bib, 逐条 arXiv/DOI 元数据验证
  │  --bib PATH       BibTeX 文件路径 (默认自动探测)
  │  --quick          跳过 HTTP 可达性检查
  │  --json           输出 JSON
  │
  ├─ audit store ─────────────────────────────────────────────
  │  跨库交叉验证
  │  --stores JSONL  逗号分隔的 JSONL 存储路径
  │  --target KEY    目标 refs.jsonl
  │
  ├─ audit notebook ──────────────────────────────────────────
  │  扫描 .ipynb 引用
  │  --dir PATH      Notebook 目录
  │
  ├─ audit citations ─────────────────────────────────────────
  │  L1/L2/L3 引用验证 (原有功能)
  │  --source s2|openalex|auto  验证来源
  │  --list FILE     引用列表 (CSV/JSONL)
  │  --threshold 0.70 相似度阈值
  │
  ├─ audit traceability ──────────────────────────────────────
  │  全链路溯源: bib → store → notebook → L1/L2/L3
  │  --quick          快速模式 (跳过 HTTP)
  │  --json           JSON 输出
  │  --report PATH   审计报告输出路径
  │
  └─ audit run ──────────────────────────────────────────────
      (默认) 全量审计: 检测 repo + 自动遍历所有层
      --repo PATH     指定仓库根目录
```

## 三、数据流

```
references.bib / refs.jsonl
       │
       ▼
  ┌─────────────┐     ┌──────────────┐
  │ bib.py      │────▶│ store.py     │────▶ 跨库交叉矩阵
  │ arXiv API   │     │ JSONL 加载   │
  │ DOI.org     │     │ coc × fusion │
  └─────────────┘     └──────────────┘
       │                      │
       ▼                      ▼
  ┌─────────────┐     ┌──────────────┐
  │ notebook.py │     │ l1_local.py  │
  │ .ipynb      │     │ SQLite 存在  │
  │ arXiv/DOI   │     │              │
  └─────────────┘     └──────┬───────┘
                              │ fallback
                              ▼
                      ┌──────────────┐
                      │ l2_s2.py     │
                      │ S2 API       │
                      └──────┬───────┘
                              │ fallback
                              ▼
                      ┌──────────────┐
                      │ l3_openalex  │
                      │ OpenAlex API │
                      └──────────────┘
                              │
                              ▼
                      ┌──────────────┐
                      │ report.py    │
                      │ JSON audit   │
                      └──────────────┘
```

## 四、实现计划

| Phase | 内容 | 涉及文件 | 预期工时 |
|:-----|:------|:---------|:--------:|
| **P1** | 创建 `audit/` 包 + 迁移 citation_audit.py | 新建 8 文件 | ~2h |
| **P2** | 移植 bib.py + store.py + notebook.py | 合并 coc verify.py | ~1h |
| **P3** | 实现 traceability.py 全链路引擎 | 整合所有层 | ~1h |
| **P4** | CLI 集成 → `hfpclawer audit` | cli.py | ~0.5h |
| **P5** | 测试 + 文档 + 双仓库部署 | tests/, docs/ | ~1h |

## 五、接口设计

### Python API

```python
from hfpclawer.audit import run_traceability

# 全量 traceability 审计
report = run_traceability(
    repo_root="/path/to/coc-inverse-agent",
    bib_path="data/references/references.bib",
    cross_stores={"coc": "data/references/refs.jsonl",
                  "fusion": "~/fusion/data/live/arxiv-all.jsonl"},
    notebook_dirs=["notebooks/"],
    quick=True,                    # 跳过 HTTP
)
print(report["summary"])
# → {"total": 215, "matched": 204, "in_notebooks": 1, ...}
```

### JSON 输出格式 (标准化)

```json
{
  "generated_at": "2026-07-03T20:00:00Z",
  "repo": "coc-inverse-agent",
  "layers_used": ["bib", "store", "notebook", "l1_local"],
  "summary": {
    "total": 215,
    "verified": 204,
    "no_identifier": 11,
    "in_store_coc": 204,
    "in_store_fusion": 5,
    "in_notebooks": 1
  },
  "citations": [
    {
      "cite_key": "hambraeus2026_xhope",
      "arxiv_id": "2605.03910",
      "doi": "",
      "status": "VERIFIED",
      "l1_local": "FOUND",
      "bib_verified": true,
      "in_store": {"coc": true, "fusion": false},
      "citing_notebooks": [],
      "reachable": {"arXiv abstract": true}
    }
  ],
  "cross_reference_matrix": {
    "coc_only": 199,
    "coc_and_fusion": 5,
    "fusion_only": 0,
    "neither": 11
  }
}
```

## 六、向后兼容

| 旧路径 | 新路径 | 兼容期 |
|:-------|:-------|:------|
| `hfpclawer.citation_audit` | `hfpclawer.audit.citation` | v0.8.x 保留重定向 |
| `hfpclawer.citation_audit_oa` | `hfpclawer.audit.l3_openalex` | v0.8.x |
| `hfpclawer.citation_audit_s2` | `hfpclawer.audit.l2_s2` | v0.8.x |
| `hfpclawer.audit.run_audit` | `hfpclawer.audit.run_audit` (增强) | 原位升级 |
| `hfpclawer.__version__` | 不变 | 永久 |

---

> **计划状态**: ✅ 方案已定，等待确认后实施。
> **涉及版本**: hfpclawer v0.8.0 (当前 v0.7.2)
