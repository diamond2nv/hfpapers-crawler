# 大规模神经算子论文爬取 + 文献检索 Plan

**目标**: 爬取 2017 年以来神经算子和 PDE 代理模型论文，去重、交叉验证 DOI 提升学术置信度

## 预算

- LLM Token: 1000 万（DeepSeek ¥28/M in, ¥4.2/M out, 约 ¥280 够 100 篇深度分析）
- 我实际用 0 token（纯程序化 + paper_store SQLite）
- 子代理用 DeepSeek，每次分析 1 篇论文约 5K in + 1K out = ¥0.0017
- 100 篇 ≈ ¥0.17

## 策略

### Phase 1: 多维度搜索（纯程序化）

用 project 自带的搜索工具分维度搜：

1. **arXiv API**（`export.arxiv.org`）— 主源，直接搜摘要
2. **HF Papers CLI**（`hf papers search`）— 辅助源

搜索维度（8 组查询）:

| # | 查询 | 原因 |
|---|------|------|
| 1 | `\"neural operator\" AND (PDE OR \"partial differential equation\")` | 核心 |
| 2 | `\"Fourier Neural Operator\" OR FNO` | FNO 系列 |
| 3 | `DeepONet OR \"deep operator network\"` | DeepONet 系列 |
| 4 | `\"physics-informed neural\" AND operator` | PINN + 算子 |
| 5 | `\"operator learning\" AND PDE` | 广泛搜索 |
| 6 | `\"neural surrogate\" AND (PDE OR simulation)` | 代理模型 |
| 7 | `\"foundation model\" AND (PDE OR simulation)` | 基础模型 |
| 8 | `\"fluid dynamics\" AND (\"neural network\" OR \"deep learning\")` | 流体方向 |

每维 top-100，去重后约 300-500 篇唯一。

### Phase 2: SQLite 持久化 + Dedup（纯程序化）

- 用 `paper_store.py` 的 `ensure_paper()` 写入
- arXiv ID 自动去重
- 每个 paper 加标识符

### Phase 3: Crossref 交叉验证（0 token）

- paper_store 自带的 `CrossrefClient.cross_verify()` 自动验证
- 标题 → DOI
- 已有验证逻辑，不需要额外 token

### Phase 4: LLM 论文分析（子代理）

对每篇论文，子代理分析（5K in + 1K out）:

1. 读取 arXiv 摘要
2. 判断是否真正相关（神经算子/PDE/代理模型）
3. 提取创新点和方法
4. 写入结构化笔记

### Phase 5: Wiki 输出

格式: `concepts/NeuralOperator/[year]/[arxiv_id].md`

## 文件路径

- 项目: `~/Gitlab/Agentic4Sci/hfpapers-clawler`
- 配置: `config.yaml`
- SQLite: `data/papers.db`
- PDF: `pdfs/`
- 笔记: `md_extracts/`
