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

### 3. 参照系与边界

- Deep Research 四步闭环（Act→Observe→Optimize→Remember）= 我们已有 GOAL 三 loop + TrajectoryStore + 验证门禁——**不新增抽象**，hfpapers 只承担 Observe 数据层
- SKILL.state × HL 互补（执行时显式状态 / 迭代间记账）——hfpapers 恰好两端都要：运行时状态（papers.db）+ 迭代记账（ledger）
- 一致性路由的工程化边界：冲突标记 suspect ≠ 自动删除（保留证据链，人工裁决——与 wiki 时间门控纪律一致）
- 设计约束：公开 repo 脱敏纪律不变；0.16.x 随 Hermes 生态稳定再定（v0.21 Pantheon 2026-08-31 刚发布，本机 0.20.6 未升级）
