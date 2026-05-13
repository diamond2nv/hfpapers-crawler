# Large-Scale Neural Operator Paper Crawling + Literature Search Plan

**Goal**: Crawl neural operator and PDE surrogate model papers since 2017, deduplicate, cross-validate DOI for higher academic confidence

## Budget

- LLM Token: 10 million (DeepSeek ¥28/M in, ¥4.2/M out, ~¥280 enough for 100 deep analyses)
- I actually use 0 token (purely programmatic + paper_store SQLite)
- Sub-agents use DeepSeek, each paper analysis ~5K in + 1K out = ¥0.0017
- 100 papers ≈ ¥0.17

## Strategy

### Phase 1: Multi-Dimensional Search (Purely Programmatic)

Use the project's built-in search tools across dimensions:

1. **arXiv API** (`export.arxiv.org`) — Primary source, directly search abstracts
2. **HF Papers CLI** (`hf papers search`) — Auxiliary source

Search dimensions (8 query groups):

| # | Query | Reason |
|---|-------|--------|
| 1 | `\"neural operator\" AND (PDE OR \"partial differential equation\")` | Core |
| 2 | `\"Fourier Neural Operator\" OR FNO` | FNO series |
| 3 | `DeepONet OR \"deep operator network\"` | DeepONet series |
| 4 | `\"physics-informed neural\" AND operator` | PINN + operator |
| 5 | `\"operator learning\" AND PDE` | Broad search |
| 6 | `\"neural surrogate\" AND (PDE OR simulation)` | Surrogate models |
| 7 | `\"foundation model\" AND (PDE OR simulation)` | Foundation models |
| 8 | `\"fluid dynamics\" AND (\"neural network\" OR \"deep learning\")` | Fluids direction |

Top-100 per dimension, ~300-500 unique after dedup.

### Phase 2: SQLite Persistence + Dedup (Purely Programmatic)

- Write via `paper_store.py`'s `ensure_paper()`
- Auto-dedup by arXiv ID
- Add identifiers for each paper

### Phase 3: Crossref Cross-Validation (0 tokens)

- `paper_store`'s built-in `CrossrefClient.cross_verify()` auto-validates
- Title → DOI
- Existing validation logic, no extra tokens needed

### Phase 4: LLM Paper Analysis (Sub-agents)

For each paper, sub-agent analyzes (5K in + 1K out):

1. Read arXiv abstract
2. Determine if actually relevant (neural operator/PDE/surrogate model)
3. Extract innovations and methods
4. Write structured notes

### Phase 5: Wiki Output

Format: `concepts/NeuralOperator/[year]/[arxiv_id].md`

## File Paths

- Project: `~/Gitlab/Agentic4Sci/hfpapers-clawler`
- Config: `config.yaml`
- SQLite: `data/papers.db`
- PDF: `pdfs/`
- Notes: `md_extracts/`
