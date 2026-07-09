# Knowledge Graph Layer — Implementation Plan (v0.10.0)

> Add a graph layer connecting people, papers, journals, institutions, and geography.
> Build on the v0.9.x NLP foundation (innovation keywords, auto-tags).

---

## Overview

**Goal:** Transform hfpclawer from a paper pipeline into a queryable knowledge graph.

**Deliverable:** `hfpclawer graph {build, stats, person, community, path, viz, export}`

**Target:** v0.10.0 (Phase 1: Build + Schema)

---

## Files to Create

### Module: `hfpapers/graph/`

| File | Purpose | Lines (est.) |
|:-----|:--------|:------------:|
| `__init__.py` | Public API, `GraphBuilder` class | ~150 |
| `schema.py` | `NodeType`, `EdgeType` enums, helper utils | ~80 |
| `sources/zotero.py` | Parse Zotero items → graph nodes/edges | ~200 |
| `sources/wiki.py` | Parse wiki/people/ → person/institution nodes | ~150 |
| `sources/paper_store.py` | Add paper_store metadata to graph | ~80 |
| `build_graph.py` | Orchestrate sources, dedup, build nx.Graph | ~200 |
| `persist.py` | Save/load graph (GraphML, pickle, GEXF) | ~100 |
| `analyze.py` | Centrality, community, ego network, path | ~250 |
| `viz.py` | Plotly interactive HTML + pydot static export | ~250 |
| `cli.py` | CLI subcommand registration | ~150 |
| **Total** | | **~1,610** |

### Configuration

- `pyproject.toml` — add `graph` and `graph-viz` optional deps
- `AGENTS.md` — update with graph module docs

---

## Module Details

### `schema.py`

```python
from enum import Enum, auto

class NodeType(Enum):
    PERSON = auto()
    PAPER = auto()
    JOURNAL = auto()
    INSTITUTION = auto()
    CITY = auto()
    COUNTRY = auto()
    TOPIC = auto()

class EdgeType(Enum):
    AUTHOR_OF = auto()
    PUBLISHED_IN = auto()
    AFFILIATED_WITH = auto()
    LOCATED_IN = auto()
    BELONGS_TO = auto()
    ABOUT_TOPIC = auto()
    CO_AUTHOR = auto()

# Node type → display color/icon mapping
NODE_STYLE = {
    NodeType.PERSON:    {"color": "#4a9eff", "size": 15, "shape": "circle"},
    NodeType.PAPER:     {"color": "#6bcb77", "size": 8,  "shape": "square"},
    NodeType.JOURNAL:   {"color": "#ffd93d", "size": 10, "shape": "diamond"},
    NodeType.INSTITUTION: {"color": "#ff6b6b", "size": 12, "shape": "triangle-up"},
    NodeType.CITY:      {"color": "#c084fc", "size": 6,  "shape": "circle"},
    NodeType.COUNTRY:   {"color": "#f472b6", "size": 7,  "shape": "circle"},
    NodeType.TOPIC:     {"color": "#34d399", "size": 5,  "shape": "cross"},
}

def node_id(ntype: NodeType, key: str) -> str:
    """Generate a unique, deterministic node ID. e.g. 'person:li-shen'"""
    return f"{ntype.name.lower()}:{_slugify(key)}"

def _slugify(s: str) -> str:
    """Lowercase, replace spaces/special chars with hyphens."""
    import re
    s = s.lower().strip()
    s = re.sub(r'[^a-z0-9\-\u4e00-\u9fff]', '-', s)
    s = re.sub(r'-+', '-', s)
    return s.strip('-')
```

### `build_graph.py` — Node/Edge Creation

**Node dedup strategy:**
- Person: (last_name.lower, first_initial) → if same, try affiliation match
- Paper: arXiv ID > DOI > title hash
- Institution: name.lower().strip()
- City: name + country
- Journal: name.lower().strip()

**Edge creation:**
- AUTHOR_OF: for each creator in Zotero item → Person (create if new) → Paper
- PUBLISHED_IN: Paper → Journal (from publicationTitle + ISSN)
- AFFILIATED_WITH: Person → Institution (from creator.affiliation)
- ABOUT_TOPIC: Paper → Topic (from extra.innovation_tags)
- CO_AUTHOR: derived — for each paper with N authors, create N×(N-1)/2 edges

**Institution → City mapping** (hardcoded for known institutions):
```python
INSTITUTION_CITY = {
    "zhejiang lab": ("Hangzhou", "China"),
    "zhejiang university": ("Hangzhou", "China"),
    "zju": ("Hangzhou", "China"),
    "中国科学院": ("Beijing", "China"),
    "中科院": ("Beijing", "China"),
    "chinese academy of sciences": ("Beijing", "China"),
    "ustc": ("Hefei", "China"),
    "university of science and technology of china": ("Hefei", "China"),
    "nanyang technological university": ("Singapore", "Singapore"),
    "ntu": ("Singapore", "Singapore"),
}
```

### `sources/zotero.py` — Zotero Parser

Given a Zotero item dict:
```python
def parse_item(item: dict) -> tuple[list[NodeDef], list[EdgeDef]]:
    """Parse one Zotero item → graph nodes and edges.

    Returns:
        (nodes, edges) where each is a list of (type, id, attrs) tuples.
    """
    data = item.get("data", {})
    key = data.get("key", "")
    title = data.get("title", "")
    pub_title = data.get("publicationTitle", "") or data.get("bookTitle", "")
    date = data.get("date", "")
    extra = data.get("extra", "")
    doi = data.get("DOI", "")
    issn = data.get("ISSN", "")
    item_type = data.get("itemType", "")
    creators = data.get("creators", []) or []

    nodes, edges = [], []

    # Paper node
    paper_id = node_id(NodeType.PAPER, f"zotero:{key}")
    nodes.append((NodeType.PAPER, paper_id, {
        "label": title[:60],
        "title": title,
        "year": _extract_year(date),
        "doi": doi,
        "type": item_type,
    }))

    # Creator → Person nodes + AUTHOR_OF edges
    for i, creator in enumerate(creators):
        last = (creator.get("lastName") or "").strip()
        first = (creator.get("firstName") or "").strip()
        if not last:
            continue
        person_id = node_id(NodeType.PERSON, f"{last.lower()}-{first[:2].lower()}")
        nodes.append((NodeType.PERSON, person_id, {
            "label": f"{last}, {first[:20]}",
            "last_name": last,
            "first_name": first,
        }))
        edges.append((EdgeType.AUTHOR_OF, person_id, paper_id, {"position": i}))

        # Affiliation → Institution
        affil = creator.get("affiliation", "") or creator.get("affiliation", [])
        if isinstance(affil, list):
            affil = " ".join(affil)
        affil = affil.strip()
        if affil:
            inst_id = node_id(NodeType.INSTITUTION, affil)
            nodes.append((NodeType.INSTITUTION, inst_id, {"label": affil}))
            edges.append((EdgeType.AFFILIATED_WITH, person_id, inst_id, {}))

    # Journal node + PUBLISHED_IN edge
    if pub_title:
        journal_id = node_id(NodeType.JOURNAL, pub_title)
        nodes.append((NodeType.JOURNAL, journal_id, {
            "label": pub_title[:40],
            "issn": issn,
        }))
        edges.append((EdgeType.PUBLISHED_IN, paper_id, journal_id, {"year": _extract_year(date)}))

    return nodes, edges
```

### `analyze.py` — Graph Analytics

```python
def degree_centrality(G: nx.Graph) -> dict:
    """Return degree centrality for all nodes."""
    return nx.degree_centrality(G)

def betweenness_centrality(G: nx.Graph) -> dict:
    """Betweenness centrality (bridging researchers)."""
    return nx.betweenness_centrality(G, weight="weight")

def pagerank(G: nx.Graph) -> dict:
    """PageRank on the co-authorship subgraph."""
    return nx.pagerank(G, weight="count")

def louvain_communities(G: nx.Graph) -> list[set]:
    """Community detection using Louvain algorithm."""
    try:
        from networkx.algorithms.community import louvain_communities
        return louvain_communities(G, weight="weight")
    except ImportError:
        from networkx.algorithms.community import greedy_modularity_communities
        return list(greedy_modularity_communities(G, weight="weight"))

def ego_network(G: nx.Graph, person_key: str, depth: int = 1) -> nx.Graph:
    """Extract ego network for a researcher."""
    return nx.ego_graph(G, person_key, radius=depth)

def shortest_path(G: nx.Graph, source: str, target: str) -> list:
    """Find shortest collaboration path between two researchers."""
    return nx.shortest_path(G, source=source, target=target)
```

### `viz.py` — Plotly Interactive

```python
import plotly.graph_objects as go
import networkx as nx

def plot_interactive(G: nx.Graph, output: str = "graph_network.html"):
    """Generate interactive HTML graph with:
    - Spring layout (nx.spring_layout)
    - Node color by type (NODE_STYLE mapping)
    - Node size by degree centrality
    - Hover text with metadata
    - Edges colored by type
    """
    pos = nx.spring_layout(G, k=0.3, iterations=50, seed=42)
    # ... build edge_trace + node_trace with go.Scatter ...
    fig = go.Figure(data=[edge_trace, node_trace], layout=layout)
    fig.write_html(output)
```

---

## CLI Implementation

Add `graph` subcommand to `hfpapers/cli.py`:

```python
@app.command()
def graph(
    action: str = typer.Argument("stats", help="build | stats | person | community | path | viz | export"),
    arg: str = typer.Argument("", help="Person name, node key, or output path"),
    limit: int = typer.Option(200, "--limit", "-l", help="Max Zotero items"),
    depth: int = typer.Option(1, "--depth", "-d", help="Ego network depth"),
    force: bool = typer.Option(False, "--force", "-f", help="Rebuild graph"),
    output: str = typer.Option("", "--output", "-o", help="Output path"),
    fmt: str = typer.Option("html", "--format", help="Export format: dot/gexf/graphml/png/svg"),
):
    """Knowledge graph operations."""
    from hfpapers.graph.cli import dispatch
    dispatch(action, arg, limit=limit, depth=depth, force=force, output=output, fmt=fmt)
```

---

## Testing

| Test | What it covers |
|:-----|:---------------|
| `test_graph_schema.py` | NodeType/EdgeType enums, node_id generation |
| `test_graph_parse_zotero.py` | Zotero item → nodes/edges extraction |
| `test_graph_build.py` | Full build from mock data |
| `test_graph_analyze.py` | Centrality, community, ego network |
| `test_graph_cli.py` | CLI dispatch, output |

---

## Timeline

| Step | Est. time | Depends on |
|:-----|:---------:|:-----------|
| schema.py | 30 min | — |
| sources/zotero.py | 1.5 h | Zotero local API access |
| sources/wiki.py | 1 h | wiki/people/ file reading |
| sources/paper_store.py | 30 min | paper_store connection |
| build_graph.py | 2 h | all sources done |
| persist.py | 30 min | build_graph.py |
| analyze.py | 1.5 h | build_graph.py |
| viz.py | 2 h | build_graph.py |
| cli.py + wiring | 1 h | all modules |
| Tests | 2 h | all modules |
|| **Total** | **~12 h** | |

---

## Cross-Repo Coordination: JSONL Exchange Protocol

hfpclawer builds **Subgraph A** (academic output: papers, people, journals, institutions).
hedge builds **Subgraph B** (discipline terminology: terms, formulas, chunks) +
**Subgraph C** (Wikipedia). JSONL is the bridge.

### JSONL Schema

```jsonl
# Node record (one per line)
{"type":"node","id":"paper:2501.01934","node_type":"PAPER",
 "label":"Fourier Neural Operator for Parametric PDEs",
 "attrs":{"title":"...","year":2025,"doi":"10.xxx","arxiv_id":"2501.01934"}}

# Edge record
{"type":"edge","source":"person:li-shen","target":"paper:2501.01934",
 "edge_type":"AUTHOR_OF","attrs":{"position":1}}

# Bridge edge: hfpclawer Subgraph A → hedge Subgraph B
{"type":"edge","source":"paper:2501.01934","target":"topic:fourier-neural-operator",
 "edge_type":"ABOUT_TOPIC","attrs":{"tfidf":0.85}}
```

### Node Types (Subgraph A)

| node_type | id prefix | attrs |
|:----------|:----------|:------|
| `PERSON` | `person:` | last_name, first_name, affiliations, orcid |
| `PAPER` | `paper:` | title, year, doi, arxiv_id, abstract, isbn |
| `JOURNAL` | `journal:` | name, issn |
| `INSTITUTION` | `inst:` | name, city, country |
| `CITY` | `city:` | name, country, lat, lng |
| `COUNTRY` | `country:` | name, code |
| `TOPIC` | `topic:` | keyword (from spaCy innovation_tags) |

### Edge Types (Subgraph A → B bridges)

| edge_type | Source → Target | Meaning |
|:----------|:---------------|:--------|
| `ABOUT_TOPIC` | PAPER → TOPIC | Paper's research topic (from innovation_tags) |
| `PUBLISHED_IN` | PAPER → JOURNAL | Journal venue |
| `AUTHOR_OF` | PERSON → PAPER | Authorship |
| `AFFILIATED_WITH` | PERSON → INSTITUTION | Affiliation |
| `LOCATED_IN` | INSTITUTION → CITY | Geography |
| `BELONGS_TO` | CITY → COUNTRY | Geography |
| `CO_AUTHOR` | PERSON → PERSON | Derived co-authorship |

### File Convention

```bash
# Shared directory (NAS or local)
~/data/kg/
├── subgraph_a.jsonl    # hfpclawer graph export → academic graph
├── subgraph_b.jsonl    # hedge → domain terminology + formulas
├── subgraph_c.jsonl    # hedge → Wikipedia entities
└── merged/             # Combined output

# Commands
hfpclawer graph export --format jsonl -o ~/data/kg/subgraph_a.jsonl
hedge knowledge import --from-jsonl ~/data/kg/subgraph_a.jsonl
```
