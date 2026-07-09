# hfpclawer v0.10.x Roadmap — Knowledge Graph Layer

> Academic knowledge graph connecting people, papers, journals, institutions, and geography.
> Target version: v0.10.0 (next major iteration after v0.9.x NLP)

---

## Why v0.10?

Current v0.9.x focuses on **paper pipeline** (search → download → ingest → annotate → audit).
v0.10.x adds a **graph layer** that connects isolated data points into a queryable,
visualizable knowledge graph.

The result: instead of searching individual papers or people, you can ask
"who in our network publishes in this journal?" or "show me all collaborators
within 2 hops of Li Shen" or "which cities do our research partners cluster in?"

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

### Phase 1 — Graph Build & Schema (v0.10.0) ✅ Target: July 2026

| Module | Deliverable |
|:-------|:------------|
| `hfpapers/graph/schema.py` | Node/Edge type enums (Person, Paper, Journal, Institution, City, Country, Topic) |
| `hfpapers/graph/build_graph.py` | Build `nx.Graph` from Zotero API + wiki/people/ + paper_store |
| `hfpapers/graph/__init__.py` | `GraphBuilder` class: orchestrate sources, dedup, persist |
| CLI: `hfpclawer graph build` | One-command build from local data sources |
| CLI: `hfpclawer graph stats` | Node/edge counts, density, degree distribution |

**Data sources:**
- Zotero local API (`/api/users/0/items`): creators → Person, publicationTitle → Journal, extra → Topic
- wiki/people/*.md: person metadata (affiliation, ORCID, research interests)
- paper_store SQLite: additional paper metadata + innovation_tags

### Phase 2 — Analysis (v0.10.1)

| Module | Deliverable |
|:-------|:------------|
| `hfpapers/graph/analyze.py` | Centrality (degree, betweenness, PageRank), community detection (Louvain), ego network |
| CLI: `hfpclawer graph person <name>` | Show ego network for a person |
| CLI: `hfpclawer graph community` | Detect and display research communities |
| CLI: `hfpclawer graph path <A> <B>` | Shortest path between two researchers |

### Phase 3 — Visualization (v0.10.2)

| Module | Deliverable |
|:-------|:------------|
| `hfpapers/graph/viz/plotly.py` | Interactive HTML (node color=type, size=centrality, hover=metadata) |
| `hfpapers/graph/viz/pydot.py` | Static PNG/SVG export via Graphviz |
| `hfpapers/graph/export.py` | Export GraphML (→ Gephi), GEXF, DOT |
| CLI: `hfpclawer graph viz` | Generate plotly_network.html |
| CLI: `hfpclawer graph export --format dot --output graph.dot` | Export for external tools |

---

## Technology Stack

| Tier | Package | License | Role |
|:-----|:--------|:--------|:-----|
| Core | `networkx>=3.0` | BSD | Graph data structure, algorithms, I/O |
| Export | `pydot>=3.0` | MIT | DOT language → Graphviz rendering |
| Viz | `plotly>=5.18` | MIT | Interactive HTML visualization |
| Viz | `nxviz>=0.7` | MIT | Circos plot for co-authorship |
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
| `INSTITUTION` | Name | city, country, ror_id | Zotero creator.affiliation |
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
hfpclawer graph person "Li Shen"               # Ego network
hfpclawer graph person "Li Shen" --depth 2     # 2-hop neighbors
hfpclawer graph community                      # Louvain communities
hfpclawer graph path "Person A" "Person B"     # Shortest collaboration path

# Visualize
hfpclawer graph viz                            # → graph_network.html (Plotly)
hfpclawer graph viz --output my_graph.html     # Custom output path
hfpclawer graph viz --circos                   # Circos plot (nxviz)

# Export
hfpclawer graph export --format dot            # → graph.dot
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
 │  4. assign node attributes (type, label, color, size)       │
 │  5. persist: save GraphML / SQLite / pickle / JSONL          │
 └─────────────────────────┬───────────────────────────────────┘
                           │
           ┌───────┼───────┼───────┐───────┐
           │       │       │       │       │
           ▼       ▼       ▼       ▼       ▼
        Plotly   pydot   nxviz   analysis  JSONL
        (HTML)   (PNG)  (circos) (stats)  (→ hedge Subgraph B)
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
    "nxviz>=0.7",
    "pydot>=3.0",
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
Full schema in `docs/plans/knowledge-graph-v0.10.md#cross-repo-coordination-jsonl-exchange-protocol`.

### Commands

```bash
# hfpclawer exports Subgraph A
hfpclawer graph export --format jsonl -o ~/data/kg/subgraph_a.jsonl

# hedge imports → merges with Subgraph B+C
hedge knowledge import --from-jsonl ~/data/kg/subgraph_a.jsonl
```
