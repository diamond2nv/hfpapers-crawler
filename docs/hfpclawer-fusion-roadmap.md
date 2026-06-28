---
title: hfpclawer v0.6 融合路线 — 机械化验证 + 论文演化分析
author: 初稿
date: 2026-06-27
tags: [hfpclawer, formula-verification, citation-network, visualization, roadmap]
---

**讨论背景：**

过去几周我们在 4 个独立 repo（coilpeft, fusion-tech-intelligence, gsnv-theory, coc-inverse-agent）中反复试验并验证了多项技术。这些技术具有高度可泛化的共性，可作为 **hfpclawer** 的扩展模块加入后续版本。

当前 hfpclawer v0.5.0 功能：
- OAI-PMH 批量下载 + 断点续传
- PDF 下载（arXiv/Kaggle）
- SQLite paper_store
- Cross-Ref 集成
- MCP Server（Model Context Protocol）
- 基本数据源审计

---

## 一、机械化验证体系（proven in 3 repos）

### 1.1 Formula Registry（公式注册表）

*已在 gsnv-theory 和 coc-inverse-agent 独立实现*

标准化 JSONL 格式：
```json
{
  "id": "eq:biot-savart-segment",
  "latex": "B = \\frac{\\mu_0 I}{4\\pi d}(\\cos\\alpha_2-\\cos\\alpha_1)\\hat{\\phi}",
  "source_keys": ["Griffiths2023"],
  "verification": ["L1", "L2", "L3", "L4", "L5"],
  "dimensions": "magnetic flux density",
  "status": "verified"
}
```

可复用组件：
- `registry.py` — JSONL 读写 / schema 校验 / 版本追踪
- SymPy → LaTeX 归一化导出
- 公式与引用自动关联

### 1.2 L1→L5 五层验证管线

| 层级 | 方法 | 工具 | 已验证于 |
|:-----|:-----|:-----|:---------|
| **L1** | SymPy 符号推导 | sympy | gsnv, coc |
| **L2** | 数值验证（高精度积分 / numpy） | numpy/scipy | gsnv, coc |
| **L3** | 物理量纲检查 | **pint**（防止 μm↔m 混淆） | gsnv, coc |
| **L4** | 物理极限（远场/近场/对称性） | numpy | gsnv, coc, HBM whitepaper |
| **L5** | 奇异点检测（分母为零/奇点） | sympy/numpy | gsnv, coc |

**关键教训：** L3 pint 量纲检查无法捕获「数值级错误」（如 μm 直接写 10 而非 10⁻⁶），必须配合 L2 数值验证 + L4 量级合理性。这个三明治防御策略已在 gsnv 的 `verify_shared.py` 和 HBM whitepaper 的 `verify_whitepaper.py` 中验证。

### 1.3 Step-by-Step Derivation（逐步骤推导）

*已在 coc-inverse-agent 的 `step_by_step.py` + `derive_*.ipynb` 中实现*

每步输出：
- 输入公式 → 代数操作 → 中间结果 → 最终结果
- SymPy `sp.Eq` 中间态 → LaTeX 渲染
- 每步的来源引用（来自 registry）
- 数值代入验证

建议 hfpclawer:
- `hfpclawer.verify.derivation` — 推导引擎
- `hfpclawer.verify.registry` — 公式注册表
- `hfpclawer.verify.pipeline` — L1→L5 统一入口

---

## 二、论文引文演化分析

### 2.1 Citation Network（引文网络）

*已在 fusion-tech-intelligence 和 coc-inverse-agent 的 data/references/ 中验证*

输出格式：
- **GEXF** — Gephi 可视化（`omc_graph.gexf`）
- **GraphML** — NetworkX 通用格式
- **JSON** — 前端 D3.js 可用

字段定义：
```json
{
  "nodes": [
    {"id": "arxiv:1903.08176", "group": "nv_magnetometry", "weight": 45, "year": 2020},
    {"id": "arxiv:2603.13754", "group": "nv_sensitivity", "weight": 12, "year": 2026}
  ],
  "edges": [
    {"source": "2603.13754", "target": "1903.08176", "type": "cites", "weight": 1}
  ]
}
```

### 2.2 Author Collaboration Network（作者合作网络）

字段：
- `coauthor_count` — 共著次数
- `last_collab` — 最近合作年份
- `institution` — 所属机构
- `h_index` — 如果可获取

可视化：
- NetworkX spring layout → SVG/PDF
- 节点大小=发文数，边粗=合作次数
- 颜色=研究领域聚类

### 2.3 减论风格词云

*已验证于 coc-inverse-agent 的 `data/references/omc_wordcloud.png`*

Pipeline:
```
PaperStore → extract_keywords(tf-idf) → wordcloud.WordCloud()
→ mask(OMC形状) → arXiv风格矢量PDF
```

### 2.4 技术领域演化图

*已验证于 coc-inverse-agent 的 `docs/figures/`*

Pipeline:
```
PaperStore → group_by_year + topic_clustering → 
  year_vs_topic_heatmap (PDF)
  topic_evolution_trend (line plot)
  hub_institution_map
```

建议 hfpclawer:
- `hfpclawer.analysis.network` — 引文/作者网络
- `hfpclawer.analysis.wordcloud` — 词云生成
- `hfpclawer.analysis.trend` — 演化趋势
- `hfpclawer.analysis.export` — GEXF/GraphML/SVG 导出

---

## 三、arXiv 风格矢量 PDF 可视化

*已验证于 coc-inverse-agent 的 `docs/figures/*.pdf` + `src/coc/visualize/`*

统一渲染规范：
| 规范 | 要求 |
|:-----|:------|
| 字体 | serif（STIX / Times）、无衬线用于轴标签 |
| 格式 | **PDF 矢量**（EPS 备选） |
| 色盲友好 | 蓝-橙配色 + 标记形状区分 |
| DPI | 600 → arXiv 投稿标准 |
| 尺寸 | 单栏 3.5in, 双栏 7in |

已验证图类型：
- **Band structure**（能带图）— `bands.py`
- **Q factor heatmap**（Q值热图）— `cell_bands.py`
- **Transmission spectra**（透射谱）— `transmission.py`
- **Parameter sweep**（参数扫描）— `meep_sweep.py`
- **GOM vs parameters**（耦合率扫描）— `omc.py`

建议 hfpclawer:
- `hfpclawer.viz.style` — arXiv 样式注册
- `hfpclawer.viz.bands` — 能带
- `hfpclawer.viz.citation` — 引文网络
- `hfpclawer.viz.trend` — 趋势图
- `hfpclawer.viz.wordcloud` — 词云

---

## 四、验证体系与引文分析的耦合

最大价值在于两者的**结合**：

```
PaperStore (hfpclawer 已有)
    │
    ├── arXiv/DOI 验证 → verified_papers
    │       │
    │       ▼
    ├── Formula Registry ← 论文中的公式 → L1→L5 验证
    │       │
    │       ▼
    ├── Citation Network ← verified_papers → 引文演化
    │       │
    │       ▼
    └── Author Network ← verified_papers → 合作图谱
```

示例流程：
1. `hfpclawer crawl "NV diamond"` → 下载论文
2. `hfpclawer verify --arxiv` → 验证 arXiv/DOI
3. `hfpclawer registry build` → 从论文提取公式
4. `hfpclawer registry check L1 L2 L3` → 验证公式
5. `hfpclawer network citation` → 生成引文网络
6. `hfpclawer network authors` → 作者合作图
7. `hfpclawer viz bands` → 能带图
8. `hfpclawer report pdf` → 输出 arXiv 风格报告

---

## 五、优先级建议

| 优先级 | 功能 | 理由 |
|:-------|:-----|:------|
| **P0** | Formula Registry + L1→L5 验证 | 最成熟，3个repo已验证 |
| **P1** | Citation Network | `fusion-tech-intelligence` 有完整管线 |
| **P2** | arXiv 风格可视化 | `coc` 有完整 `visualize/` 模块 |
| **P3** | 词云 + 演化图 | 减论风格，市场差异化 |
| **P4** | Author Collaboration Network | 依赖 S2 API rate limit |

---

## 六、hfpclawer v0.6 建议包结构

```
hfpclawer/
├── __init__.py
├── audit.py                    # 已有
├── download/                   # 已有
├── verify/                     # 新增：机械化验证
│   ├── __init__.py
│   ├── registry.py             # FormulaRegistry (JSONL)
│   ├── pipeline.py             # L1→L5 统一入口
│   ├── symbolic.py             # L1 SymPy
│   ├── numerical.py            # L2 numpy
│   ├── dimensional.py          # L3 pint
│   ├── limits.py               # L4 极限/奇异点
│   ├── derivation.py           # Step-by-step
│   └── checks.py               # citation_checker 集成
├── analysis/                   # 新增：论文分析
│   ├── __init__.py
│   ├── network.py              # 引文/作者网络
│   ├── wordcloud.py            # 词云
│   ├── trend.py                # 演化趋势
│   └── export.py               # GEXF/GraphML/JSON
├── viz/                        # 新增：可视化
│   ├── __init__.py
│   ├── style.py                # arXiv 样式注册
│   ├── citation.py             # 引文网络 SVG/PDF
│   ├── trend.py                # 趋势图
│   └── wordcloud.py            # 词云
└── cli/                        # 新增命令
    ├── verify_cmd.py           # hfpclawer verify ...
    ├── network_cmd.py          # hfpclawer network ...
    └── viz_cmd.py              # hfpclawer viz ...
```

---

**讨论题：**

1. Formula Registry 是否应该独立为 PyPI 包（如 `formula-registry`）被 hfpclawer 引用？还是直接嵌入？
2. L1→L5 的 pint + SymPy 依赖较重（~50MB），是否用 lazy import + optional extras？
3. 引文网络的数据源：S2 API vs OpenAlex vs CrossRef？三者各有 rate limit
4. 可视化依赖：matplotlib（稳定）vs plotly（交互）vs 两者都支持？
5. hfpclawer 的论文下载管线是否应该内置 `references/` 目录创建（类似 gsnv 的 `refs_index.jsonl`）？
