# hfpclawer v0.10.x Roadmap — Knowledge Graph Layer

> Academic knowledge graph connecting people, papers, journals, institutions, and geography.
> Active development: v0.10.0–v0.10.4. v0.11.x planning moved to wiki.

---

## Why v0.10?

Current v0.9.x focuses on **paper pipeline** (search → download → ingest → annotate → audit).
v0.10.x adds a **graph layer** that connects isolated data points into a queryable,
visualizable knowledge graph.

The result: instead of searching individual papers or people, you can ask
"who in our network publishes in this journal?" or "show me all collaborators
within 2 hops of Jane Doe" or "which cities do our research partners cluster in?"

```
v0.9.x                  v0.10.x
──────                  ──────
papers ──────────────►  papers + people + journals + institutions + cities
tags                    graph queries
linear search           community detection
                        centrality analysis
                        interactive visualization
```

---

## Phases

### Phase 1 — Graph Build & Schema (v0.10.0) ✅ 

| Module | Deliverable |
|:-------|:------------|
| `hfpapers/graph/schema.py` | Node/Edge type enums, ID generation, style mapping |
| `hfpapers/graph/__init__.py` | `GraphBuilder` class: orchestrate sources, dedup, persist |
| CLI: `hfpclawer graph build` | One-command build from Zotero + wiki |
| CLI: `hfpclawer graph stats` | Node/edge counts, density, degree distribution |

**Data sources:** Zotero local API + wiki/people/*.md

### Phase 2 — Analysis (v0.10.1) ✅

| Module | Deliverable |
|:-------|:------------|
| `hfpapers/graph/analyze.py` | Centrality (degree, betweenness, PageRank), community detection (Louvain), ego network |
| CLI: `hfpclawer graph person <name>` | Show ego network for a person |
| CLI: `hfpclawer graph community` | Detect and display research communities |
| CLI: `hfpclawer graph path <A> <B>` | Shortest path between two researchers |

### Phase 3 — Persistence & Language Support (v0.10.2) ✅

| Module | Deliverable |
|:-------|:------------|
| `hfpapers/graph/__init__.py` | Graph pickle cache, build marker for incremental builds |
| `hfpapers/graph/sources/wiki.py` | YAML frontmatter parser, google_scholar field |
| `hfpapers/graph/__init__.py` | TOPIC auto-injection from title (spaCy NNP extraction) |
| `hfpclawer/graph_cli.py` | `cmd_person` rewrite for fuzzy Chinese/English name search |
| `config.yaml` | `graph:` section with wiki_dir, cache_path, topic_from_title |

### Phase 4 — Geo Enrichment (v0.10.3) ✅

| Module | Deliverable |
|:-------|:------------|
| `hfpapers/graph/schema.py` | New: INSTITUTION, CITY, COUNTRY NodeType + AFFILIATED_WITH, LOCATED_IN EdgeType |
| `hfpapers/graph/sources/institutions.py` | GeoCache (JSONL cache) · 39 curated institution→city/country/coords · geopy Nominatim RateLimiter · Chinese name matching |
| `hfpapers/graph/__init__.py` | Phase 5: extract institutions → geocode → enrich graph |
| `hfpclawer/graph_cli.py` | `geo stats` / `geo institutions` subcommands |
| `config.yaml` | `graph.geo` section (enabled, cache_path, use_api) |
| `pyproject.toml` | `geopy>=2.4` added to `[graph]` optional deps |

### Phase 5 — Geo Visualization & Circos (v0.10.4) ✅

| Module | Deliverable | Dependencies |
|:-------|:------------|:-------------|
| `hfpapers/graph/viz/folium.py` | Interactive institution map (MarkerCluster, popup metadata) | `folium` |
| `hfpapers/graph/viz/nxviz.py` | Circos plots for co-authorship (matplotlib polar) | `matplotlib` |
| CLI: `hfpclawer graph map` | Generate `institution_map.html` | `folium` |
| CLI: `hfpclawer graph viz --style circos` | Circos co-authorship visualization | `matplotlib` |

### Enhancement — Institution Abbreviation & Label Fix (v0.10.4+) ✅

| Fix | Description |
|:----|:------------|
| `institutions.py` | `INST_ABBREV` dict + `abbrev` node attribute for Chinese universities (USTC, PKU, etc.) |
| `nxviz.py` | Angle-aware label placement, `clip_on=False`, polar ylim expansion for long labels |
| `graph_cli.py` | Fix `output=""` overriding default path |

---

## Design Review Record

### Decision: Rule Engine for Literature Discovery & Curation

**Reviewed:** 2026-07-09
**Conclusion:** Not needed. Declined and signed off.

**Reasoning:**
The current `config.yaml`-based pipeline (search.queries + keywords + classification thresholds)
already functions as a declarative rule system appropriate for this project's scale:

| Current approach | Why it's sufficient |
|-----------------|-------------------|
| `search.queries` (40+ dimensions) | Covers discovery breadth; bottleneck is query coverage, not filter expressiveness |
| `keywords.include_high/med/low` + scoring | Linear keyword scoring handles all current filtering needs without AND/OR/NOT nesting |
| `classification.threshold_pass=30` | Simple pass/fail line works because the decision is binary (store or skip), not multi-class |
| `exclude` blacklist | Single negation check is enough; no complex exclusion patterns needed |

A full rule engine (business-rules, durable_rules, json-rules-engine) would add:
- New DSL to learn
- Rule priority/conflict resolution complexity
- ~200+ extra lines for zero improvement over current ~30-line `RelevanceDetector`

**Improvement path:** If conditional post-processing is ever needed (e.g. "if score≥60 AND has_code → high_priority"),
add a 5-line `post_rules` section in `RelevanceDetector`, not a rule engine.

*Reviewed and signed off by the project maintainer, 2026-07-09.*

---

## v0.11.x and Beyond

Future planning moved to wiki:
→ [wiki: `concepts/hfpclawer-v0.11x-plan.md`](https://<nas-dokuwiki>/doku.php?id=concepts:hfpclawer-v0.11x-plan)
(Local copy: `~/wiki/concepts/hfpclawer-v0.11x-plan.md`)

Topics covered in the wiki page:
- OWL/RDF Export (was Phase 6)
- OWL Reasoning & Consistency (was Phase 7)
- Enhanced Community Detection (was Phase 8)
- DSL-based rule system exploration (superseded by this review)
- Cross-repo integration with hedge Subgraph B+C

---

## Technology Stack

| Tier | Package | License | Role |
|:-----|:--------|:--------|:-----|
| Core | `networkx>=3.0` | BSD | Graph data structure, algorithms, I/O |
| Export | `pydot>=3.0` | MIT | DOT language → Graphviz rendering |
| Viz | `plotly>=5.18` | MIT | Interactive HTML visualization |
| Viz | `matplotlib>=3.8` | PSF | Circos plot for co-authorship |
| System | `graphviz` (apt) | EPL 1.0 | pydot rendering backend |
| Persistence | GraphML / SQLite | — | Graph serialization |

---

## Graph Schema

### Node Types

| Type | Label | Attributes | Source |
|:-----|:------|:-----------|:-------|
| `PERSON` | Name | wiki_page, orcid, affiliation, research_interests | Zotero creators + wiki/people/ |
| `PAPER` | arXiv ID / DOI | title, year, abstract | Zotero items + paper_store |
| `JOURNAL` | Name | issn | Zotero item.publicationTitle |
| `INSTITUTION` | Name | city, country, ror_id, abbrev | Zotero creator.affiliation |
| `CITY` | Name | country, lat, lng | Geocoded from institution |
| `COUNTRY` | Name | code | ISO 3166-1 alpha-2 |
| `TOPIC` | Keyword | — | innovation_tags from extra field |

### Edge Types

| Type | Source → Target | Attributes | Meaning |
|:-----|:---------------|:-----------|:--------|
| `AUTHOR_OF` | PERSON → PAPER | position (1st, last, corresponding) | Author relationship |
| `PUBLISHED_IN` | PAPER → JOURNAL | year | Publication venue |
| `AFFILIATED_WITH` | PERSON → INSTITUTION | — | Institutional affiliation |
| `LOCATED_IN` | INSTITUTION → CITY | — | Geographic location |
| `BELONGS_TO` | CITY → COUNTRY | — | Administrative boundary |
| `ABOUT_TOPIC` | PAPER → TOPIC | tfidf_score | Research topic |
| `CO_AUTHOR` | PERSON → PERSON | count | Derived co-authorship edge |

---

## CLI Usage

```bash
# Build
hfpclawer graph build                          # Build from Zotero + wiki
hfpclawer graph build --force                  # Rebuild from scratch
hfpclawer graph build --limit 500              # Limit Zotero items scanned

# Stats
hfpclawer graph stats                          # Summary statistics
hfpclawer graph stats --detail                 # Per-type counts

# Query
hfpclawer graph person "Jane Doe"               # Ego network
hfpclawer graph person "Jane Doe" --depth 2     # 2-hop neighbors
hfpclawer graph community                      # Louvain communities
hfpclawer graph path "Person A" "Person B"     # Shortest collaboration path

# Visualize
hfpclawer graph viz                            # → circos.png
hfpclawer graph map                            # → institution_map.html
hfpclawer graph viz --output my_circos.png     # Custom output path

# Export
hfpclawer graph export --format jsonl          # → Subgraph A JSONL
hfpclawer graph export --format gexf           # → graph.gexf (Gephi)
hfpclawer graph export --format png            # → graph.png (via pydot)
```

---

## Data Flow

```
 Zotero local API           wiki/people/*.md          paper_store
       │                         │                       │
       ▼                         ▼                       ▼
 ┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐
 │ ZoteroSource  │    │   WikiSource      │    │ PaperStoreSource │
 │  parse items  │    │  parse frontmatter│    │  add metadata    │
 │  creators  →   │    │  → Person nodes  │    │  → Paper nodes   │
 │  papers    →   │    │  → Institution   │    │  → Topic nodes   │
 │  journals  →   │    │  → City/Country  │    └──────────────────┘
 │  topics    →   │    └──────────────────┘
 └──────┬────────┘
        │
        ▼
 ┌─────────────────────────────────────────────────────────────┐
 │                    GraphBuilder                              │
 │  1. dedup by arxiv_id / doi / person_name + affiliation     │
 │  2. add edges (author_of, published_in, affiliated_with)     │
 │  3. derive co_author edges from shared papers                │
 │  4. assign node attributes (type, label, color, size, abbrev)│
 │  5. persist: save pickle / JSONL                             │
 └─────────────────────────┬───────────────────────────────────┘
                           │
           ┌───────┼───────┼───────┐───────┐
           │       │       │       │       │
           ▼       ▼       ▼       ▼       ▼
        Plotly   pydot   Circos  analysis  JSONL
        (HTML)   (PNG)   (.png)  (stats)  (→ hedge Subgraph B)
```

---

## Dependencies

```toml
[project.optional-dependencies]
graph = [
    "networkx>=3.0",
]
graph-viz = [
    "hfpclawer[graph]",
    "plotly>=5.18",
    "matplotlib>=3.8",
    "pydot>=3.0",
    "folium>=0.16",
]
```

System dependency: `sudo apt install graphviz`

---

## Cross-Repo Coordination

### Three-Subgraph Architecture

```
hfpclawer (this repo)         hedge (~/Documents/Gitlab/forgejo-self-host/hedge/)
    Subgraph A                    Subgraph B + Subgraph C
    ┌─────────────────┐          ┌──────────────────────────────┐
    │ Academic Output  │────about_topic────▶│ Discipline Terminology│
    │ Paper/Book       │          │ Term, Formula, Chunk        │
    │ Person           │          │ Wikipedia Article, Category │
    │ Journal          │          └──────────────────────────────┘
    │ Institution      │
    │ City/Country     │
    └───────┬─────────┘
            │ JSONL (~/data/kg/subgraph_a.jsonl)
            ▼
      hedge knowledge import --from-jsonl
```

### Exchange Format

JSONL (one JSON object per line) with two record types:
- `{"type":"node","id":"...","node_type":"PAPER","label":"...","attrs":{...}}`
- `{"type":"edge","source":"...","target":"...","edge_type":"AUTHOR_OF","attrs":{...}}`

Bridge edge `ABOUT_TOPIC` (PAPER → TOPIC) connects Subgraph A to Subgraph B.

### Commands

```bash
# hfpclawer exports Subgraph A
hfpclawer graph export --format jsonl -o ~/data/kg/subgraph_a.jsonl

# hedge imports → merges with Subgraph B+C
hedge knowledge import --from-jsonl ~/data/kg/subgraph_a.jsonl
```

---

## Future Directions

### Ω-Architect RL + Agent Loop — 分层导航

当 omega-architect 的 RL+Agent+编辑循环+编译循环模式集成后，
hfpclawer 的知识发现将从平面检索升级为**分层导航**：

| 层级 | 类比 | hfpclawer 对应 | 后端 |
|:-----|:------|:---------------|:------|
| **轨迹层** | 车道级导航 | norm_checker 约束搜索空间 | hedge |
| **策略层** | 路线规划 | RL 奖励引导高价值探索 | omega-architect |
| **价值层** | 目的地验证 | Lean 形式化确保推理链正确 | omega-architect + lean-lsp-mcp |

**前置条件：** hedge Layer 1 (kg ingest/query) + Layer 2 (norm extension) 接口稳定。
详见 `hedge/spec/INTERFACE_VISION.md`。

### PM 方法论集成

hfpclawer 作为知识底层，可为结构化决策提供支撑：

```
pm-skills 需求 → hfpclawer store/图谱 → 数据支撑 → Hermes 输出方案
                        ↓
               hedge norm_checker → 合规验证
                        ↓
               omega-architect → 形式化保证
```

详见 `pm-skills-localization` skill + `~/wiki/concepts/pm-skills-localization.md`。

---

## 2026-09: v0.15.x 搜广推增强 + v0.16.x Hermes Pantheon 适配

> 原则：**change little for best**——90% 是部署/配置，代码改动最小化；
> 已有模块复用优先，不引入新依赖、不做过度设计（拒绝清单见下）。

### 0. 基线核验（2026-09-03）

- ⚠️ **版本未同步**：pyproject.toml = 0.15.2，但 git 已有 `e08f922 "v0.15.3: hub-guided layered graph expansion (SimClusters inspired)"`——违反 AGENTS.md「版本号必须来自 pyproject.toml」纪律，先修
- 已有可复用资产：`hfpclawer/_text_similarity.py` · `hfpapers/graph/`（analyze + HubGuidedExpander）· `relevance` 字段 · `config.yaml search.queries`（带 weight 的查询历史=最强隐式兴趣信号）· Zotero LAN API（zotero-local-api skill 场景 C）

### 1. v0.15.x — 版本纪律修复 + 搜广推增强（小改动路线）

| 优先级 | 项 | 内容 | 规模 |
|:--|:--|:--|:--|
| P0 | 版本纪律修复 | pyproject → 0.15.3 + `scripts/release.sh 0.15.3` | 分钟级 |
| P1 | `hfpclawer recommend` 一期 | config search.queries 关键词 ✕ `_text_similarity` 标题/摘要 top-N——**纯复用零新依赖** | ~100 行 |
| P2 | 评估框架 | golden set 50 对人工标注（相关/无关）+ recall@10 基线（tests/ 固定数据，不进库）| ~150 行 |
| P3 | 二期（可选）| Zotero **Favor** 显式标签为隐式反馈源（复用 zotero-local-api LAN 链路）+ 推荐理由（引用关系 > 关键词 > Zotero 备注/Extra）| ~200 行 |

**拒绝清单**（无行为数据规模，避免过度设计）：真 SimClusters 实现 · 协同过滤 · 在线学习 · A/B 测试框架 · 独立推荐服务化。

### 2. v0.16.x — 技术融合版（2026-09 新方法论融入，替换原 Pantheon 泛化段）

> 2026-09-03 优化：把最近沉淀的技术（SKILL.state / HL ledger / 0-token monitor / 一致性路由）
> 映射到 hfpapers-crawler 的具体落点——v0.16 从"Pantheon 适配"升级为
> **"state-ledger 融合版"**（适配只是部署侧的一部分）。

**技术 → 落点映射**：

| 新技术 | 落点 | 模块 |
|:--|:--|:--|
| **SKILL.state**（显式可变状态替代 append-only 历史，2608.26263）| 论文状态语义化：`pending → verified / suspect / stale` 三态显式（非 append-only 事件流）；抓取 checkpoint 显式化（graph expand-hub 已有 checkpoint——推广到 import/crawl）| `paper_store` 状态机 + `crawl` checkpoint |
| **HL ledger**（hl_benchmark/ledger.py：git_commit+diff_identifier+llm_cost+next_hypothesis）| `hfpclawer run --ledger`：每次 run 写 ledger 行（时间戳/sf_id 增量/来源/**llm_cost**/next_hypothesis）——可审计+可复现+成本追踪 | `run` 命令 + `data/ledger.jsonl` |
| **0-token monitor 分层**（Pantheon/deep-research 融合点）| `check-new [source]`：0-LLM 变动检测（时间戳/ID 比较）——cron monitor 第一层；有变化才唤醒 LLM | `check-new` 命令（复用 evolved.py 探测）|
| **一致性路由**（TTPO/无教师对齐：判断"一致性"优于判断"正确性"）| 多源元数据（arXiv/OpenAlex/Crossref）**冲突 = suspect 标记**（不进 verified 计数）——citation-audit 三源审计已做交叉，升级为状态字段而非一次性审计 | `citation-audit` → 状态回写 |
| **无教师自监督评估**（Self-OPD 思想）| golden set 自举：经人工 review 确认的论文自动沉淀为**正例池** → recall 基线随使用自动扩大（非一次性 50 对）| `tests/` golden → `data/golden_positive.jsonl` 增量 |

**Mirobody 光谱佐证**（wiki: survey-mirobody-nlp-spectrum-2026——封闭受控词表+高错误代价域的符号化设计——与论文元数据核验同构）：

| 光谱原则 | hfpapers 落点升级 |
|:--|:--|
| **符号决策/LLM 感知分界**（"model shouldn't be trusted to recite a code system"）| suspect/verified 判定=**硬谓词多源比对**（字段级精确比较），LLM 不参与元数据裁决——LLM 只做开放理解（摘要蒸馏输出结构化 JSON）|
| **abstain 一级状态**（refused ≠ 空）| 三态中 `suspect` = 显式 abstain 语义（audit 无法判定 → suspect，非"未验证"空态）——强化 0.16.0 |
| **COVERAGE_FLOOR ratchet**（黄金集只升不降）| 0.16.2 正例池升级为 **ratchet 门禁**：覆盖/召回基线只升不降，回归即失败——比"自举扩大"更严 |
| **确定性谓词链 > 学权重**（LTR 软融合被拒）| 0.16.2 推荐精排=硬谓词链（venue 白名单/年份窗/相关性阈值）——**独立佐证 roadmap 拒绝清单**（医疗高错误代价域同样弃用统计排序）|

### 2b. 信号源鲁棒性分层（2026-09-03 用户设计约束——Zotero 缺失不影响搜广推）

> 约束：搜广推信号与精度（verification）信号必须**第一方本地化于 paper_store.db**；
> Zotero local API 只是**可选增强适配器**——用户无 Zotero 时功能 100% 可用。

```
信号分层（本地优先，鲁棒性由设计保证）:
┌─ 第一方本地信号（paper_store.db + config.yaml，零外部依赖）──────────┐
│ ① search.queries（config——6 年查询历史 + weight）  → 召回种子       │
│ ② relevance 字段（打分——relevance_set_at 时间戳权威）→ 排序输入      │
│ ③ 行为信号（本地落库）：zotero_pushed_at（推送=兴趣）+                │
│    DownloadQueue 记录（下载=强兴趣）→ 需补 download_at 回写           │
│ ④ 精度信号（v0.16 state）：audit_level / suspect / stale              │
│    → 推荐门禁：suspect 不推 · stale 降权 · verified 优先               │
└──────────────────────────────────────────────────────────────────┘
┌─ 可选增强（adapter 模式，缺失降级无损）───────────────────────────────┐
│ Zotero local API（zotero-local-api 场景 C）：                          │
│   Favor 标签/Extra 备注 → 同步**回写** paper_store（favorited 列，     │
│   v0.16.1 加）→ 增强排序；无 Zotero → 仅用第一方信号，功能不减          │
└──────────────────────────────────────────────────────────────────┘
```

- **Zotero 条目过滤纪律（2026-09-03 用户约束）**：Zotero 库条目类型混杂（期刊/书/网页/报告/图片），**只有学术论文类条目对 hfpapers-crawler 有用**。sync-back 判定：
  - **identifier 判据（主）**：条目含 DOI 或 arXiv ID → 学术论文（期刊/preprint 皆可）→ 入库候选；无 ID 的网页/书籍/报告/其他 → 丢弃
  - **itemType 白名单（辅）**：journalArticle / conferencePaper 直接过；`preprint` 形态的条目以 identifier 判据为准（Zotero 类型字段不可全信，archiveID/DOI 才权威）
  - 入库匹配：arXiv ID/DOI → `get_paper_by_identifier` → 命中本地 sf_id 才写 favorited（未入库论文可选 ensure_paper 占位——二期）
  - 对齐 hfpclawer-citation-audit 既有纪律：期刊/会议/预印本显式区分，非论文条目永不混入 papers.db

- 设计原则（承 Mirobody 可移植性）：**主路径零外部依赖**——embedding/Zotero 均为 opt-in 建议层
- 方向修正：现有 zotero_pushed_at 只记录"我们→Zotero"单向推送；缺"Zotero→我们"读回（Favor 落点）——0.16.1 补 `favorited`/`favorited_at` 列 + `zotero sync-back` 命令
- 推荐管线边界：recommend 一期只用第一方信号（queries×similarity+relevance+精度门禁）——**不阻塞于 Zotero**

### 2c. 精排可训练层 + 成本追踪三层（2026-09-03 用户设计扩展）

**精排升级路径（承光谱：符号主路径不变，训练层 = opt-in 建议层）**：

```
Layer 0（默认，符号）: 召回 = config queries × _text_similarity；门禁 = 精度状态机
Layer 1（opt-in，CPU）: lightgbm LTR 排序（正例池 = 0.16.2 golden 自举 + review 正例）
                        特征 = 文本相似度 / 图中心性 / venue 白名单命中 / 年份新鲜度 /
                               查询类别匹配 —— 训练秒级，导出 ONNX 推理（毫秒）
Layer 2（远期，GPU）:   BERT 排序（需 >1k 标注才上——torch 进 [rank-gpu] extra）
换训练模型不重调符号层（可移植性——Mirobody embedding 矩阵教训：模型文件本地导出不随 wheel 分发）
```

- pyproject 新增 extra：`rank = [lightgbm, onnxruntime]`（CPU 默认）/ `rank-gpu = [hfpclawer[rank], torch]`（远期）
- 0.16.1 范围：`rank` extra + `hfpclawer rank train`（导 ONNX）+ `recommend --rank`（符号+精排双模式）

**成本追踪三层来源（ledger.llm_cost 的真实性设计——不估算）**：

```
L1 usage 直记（主，精确）: hfpclawer 自调 LLM（litellm——sniff 等）→ 响应
    usage.prompt_tokens/completion_tokens × config 单价 → ledger.llm_cost
L2 Hermes 侧归因（agent 调用时）: Hermes provider token 记录 / OTel langfuse
    trace → ledger 记 meta 链接（run_id/调用链）——不重复造轮子
    （hermes-langfuse-integration 已落地——hfpclawer 只引用）
L3 余额对账（兜底校验）: cc-switch 式余额查询——llm-api-balance-check skill
    已有 6 家余额接口 → 周期对账（ledger 累计 vs 余额下降）→ 失控预警
```

- 判定：cc-switch 余额 = 校验层（周期对账）非主源（余额含多用途误差）；L1 usage 直记最准

### 2d. 学术人脉网络的可审计推荐体系（2026-09-03 refine——hub 启发式 × 学习层融合）

> 叙事定位：hfpapers-crawler 的推荐 = **引用论文 + 学术人脉网络（author/affiliation 已在
> citation graph PERSON 节点）+ 可审计体系**——每个推荐可回答"为什么"（Mirobody 光谱：
> 可解释性 > 端点指标）。hub 启发式（v0.15.3 HubGuidedExpander）是骨架，学习层 opt-in 增强。

```
体系分层（每层保留审计轨迹）:
┌─ L0 符号层（0-token 默认，完全可审计）──────────────────────────────┐
│  HubGuidedExpander：PageRank+degree hub 评分 → 分层扩展              │
│  审计输出：每 hub 附理由（score/degree/seed→hub 路径/采纳与否）      │
│  = 引用网络的"确定性探索"——同输入必同输出，理由可复现                 │
├─ L1 学习层（opt-in，树模型可解释）───────────────────────────────────│
│  lightgbm 精排：正例 = hub 扩展采纳的论文；负例 = 同 frontier 未采纳  │
│  特征 = hub 分数/文本相似度/venue/年份/图中心性 → 树特征重要性=审计    │
├─ L2 图嵌入层（0.16.2+，自监督无标注）─────────────────────────────────│
│  LightGCN/SGL citation-graph 嵌入（节点 dropout 对比学习）            │
│  = "学出来的 hub"——嵌入相似度做图先验特征（非替代，喂给 L1）           │
│  + ModernBERT 论文编码器（CPU onnx）——文本先验                        │
└─ L3 状态层（v0.16.0 已有）────────────────────────────────────────────┘
   suspect 论文不出现在推荐候选 · verified 优先 · 人脉节点审计留痕
```

- **可审计性契约**：推荐输出必带 `why`（symbolic: hub 分数/路径 → tree: 特征贡献 top-3 → 图: 嵌入邻居）——hub 启发式从"探索策略"升级为"可审计体系的确定性骨架"
- **学习数据不造假**：正例 = 扩展实际采纳（真用户轨迹：谁被 seed 扩展选中）；负例 = frontier 截断丢弃的（假阴性有限——标注纪律同 0.16.2 golden）
- Transformer 融入定位（承 §2c 地图）：① ModernBERT 编码器 = L2 文本先验；② GNN/LightGCN = L2 图先验；③ 序列/BERT4Rec 数据到位前不做——hub 骨架让 Transformer 故事有据可依（引用网络=结构化先验，非生搬）
- 0.16.1 build 范围：L0 审计输出（expand-hub --audit）+ L1 `rank train`（lightgbm→ONNX）+ `recommend --rank` 双模式

**Hermes 侧（零代码，部署配置）**——保留原 Pantheon 段：

```
① cron + monitor + no_agent 0-token 分层: check-new 无变化 → 0-token；有变化 → LLM 摘要/相关性 → 推送
② 增量去重 = papers.db sf_id 幂等（import-cmd 已 dedup）
③ Bot Mode / Hermes Peer = 多 Agent 协作界面（配置级）
④ 兴趣进化 = 用户点赞/忽略写 Hermes MEMORY → refine search.queries weight（职责分离：记忆 Hermes 侧）
```

**v0.16.x 版本节奏建议**：
- 0.16.0「state」：论文状态三态语义 + 状态回写（citation-audit 冲突→suspect）+ 旧数据迁移
- 0.16.1「ledger」：run --ledger（llm_cost 追踪）+ check-new 命令
- 0.16.2「assess」：golden set 自举正例池 + recall 基线自动化

### 2e. 开源通用正例池（2026-09-03 用户设计约束——repo 开源 MIT，必须通用化）

> 早期构想（§2b/378 行）是单用户 golden 视角（人工 review 沉淀）。开源版升级约束：
> **无标注 · 无个人画像 · 数据不进 git · 无遥测回传** —— 任何 clone 用户零配置自举。

```
正例池 = data/positive_pool.jsonl（gitignored，append-only，每行一条样本）
行: {"arxiv_id", "label": +1|0, "layer", "weight", "ts", "source_run", "features"}

标签来源分层（权重=可信度，与用户/repo 解耦）:
  verified   +1  w=2.0  store 里 verified 状态论文（audit_level≥1，get_status 语义）← 任何用户 import+核验即有
  manual     +1  w=3.0  `pool add --via manual`（用户显式正例，最强）
  favorited  +1  w=1.5  Zotero sync-back 兴趣信号（可选——无 Zotero 不影响）
  adopted    +1  w=1.0  hub 启发式采纳（audit 行 adopted=true）——弱标签（行为克隆）
  truncated   0  w=1.0  同层截断候选（启发式拒绝）——弱负例
  suspect 论文永不入池（abstain ≠ 负例——状态语义硬门禁）

活门禁（防池污染——Mirobody COVERAGE_FLOOR ratchet 实现）:
  ① 入池：identifier 冲突检测不过 → 拒（store 已 suspect 的论文不入池）
  ② 训练时活过滤：池保留 append-only（可审计），导出时剔除当前 status==suspect
     的论文（状态可逆——清白后可复用，池不删行）
  ③ 标签裁决：同 arxiv_id 正负冲突（跨 run 决策翻转）→ 按层优先级裁决
     verified > manual > favorited > adopted > truncated——冲突不再沉默
  ④ COVERAGE_FLOOR：训练前最小样本数 + 正负双类必须齐全，回归即失败

CLI（零配置自举路径）:
  pool ingest --audit <jsonl>      audit 行汇入（adopted→+1/truncated→0；幂等去重）
  pool ingest-verified             store 里 audit_level=3 → +1 verified 层
  pool sync-favorited              favorited=1 论文 → +1 favorited 层（与 sync-back 闭环）
  pool add <aid> --via manual --reason "..."    显式正例
  pool stats                       分层分布/正负比/池大小（ratchet 可视化）
  pool export --out <train.jsonl>  活过滤后导出 → rank train 标准输入
  rank train --pool                （替代/补充 --audit：吃池导出）

开源通用性论证:
  1. 零配置自举链: import → graph expand-hub --audit → pool ingest → pool ingest-verified
     → pool stats → rank train —— 无标签/无画像/Zotero 全不需要
  2. 画像零耦合: verified/manual/adopted 层源自 store 状态与启发式决策——与 repo 无关
     （favorited 层才带兴趣，且可选）
  3. 数据安全: data/ 已 gitignored——池 100% 本地；开源不泄露用户读什么
  4. 社区可回馈: 不收集遥测——池纯本地；未来发布训练集 = 显式 `export` + 脱敏后人工决定

拒绝清单（承 §2d）: 不做在线学习（池小——每 run 全量重训足够）；不做跨用户联邦/遥测；
不做自动 prune（append-only + 训练活过滤足够——删行破坏可审计性）

### 3. 参照系与边界

- Deep Research 四步闭环（Act→Observe→Optimize→Remember）= 我们已有 GOAL 三 loop + TrajectoryStore + 验证门禁——**不新增抽象**，hfpapers 只承担 Observe 数据层
- SKILL.state × HL 互补（执行时显式状态 / 迭代间记账）——hfpapers 恰好两端都要：运行时状态（papers.db）+ 迭代记账（ledger）
- 一致性路由的工程化边界：冲突标记 suspect ≠ 自动删除（保留证据链，人工裁决——与 wiki 时间门控纪律一致）
- 设计约束：公开 repo 脱敏纪律不变；0.16.x 随 Hermes 生态稳定再定（v0.21 Pantheon 2026-08-31 刚发布，本机 0.20.6 未升级）
