# HF Papers Deep Crawler — Scrapy + requests Hybrid Architecture

## Architecture Design

```
                    ┌──────────────────────────────────┐
                    │   Search Layer (federated crawl)  │
                    │   → Multi-source multi-query      │
                    └──────────────┬───────────────────┘
                                  │ Paper metadata (dict)
                                  ▼
                    ┌──────────────────────────────────┐
                    │   Pipeline Layer (filter + save)  │
                    │ ① Dedup (hfpapers-crawled.json)   │
                    │ ② Candidate list → data/candidates│
                    └──────────────┬───────────────────┘
                                  │ Top 20 candidates
                                  ▼
                    ┌──────────────────────────────────┐
                    │   Worker Pool (3 workers)         │
                    │ ① requests download PDF (pdfs/)  │
                    │ ② pymupdf4llm → Markdown (mds/) │
                    │ ③ web_extract check GitHub code │
                    └──────────────┬───────────────────┘
                                  │ Processed paper data
                                  ▼
                    ┌──────────────────────────────────┐
                    │   Wiki Integrator (llm-wiki)      │
                    │ ① Update index.md + log.md       │
                    │ ② Create concept/person pages    │
                    │ ③ Update dedup record (crawled)  │
                    └──────────────────────────────────┘
```

## Dedup Strategy (3-Stage)

1. **Scrapy layer**: dupefilter + fingerprint cache (request fingerprints)
2. **Pipeline layer**: Compare against hfpapers-crawled.json by arxiv_id
3. **Download layer**: Check if file already exists in pdfs/ directory

## Multi-Dimension Crawl (Federated)

Crawl 5 search dimensions simultaneously, normalize each result:

1. `"neural operator" AND (PDE OR "partial differential equation")`
2. `"Fourier Neural Operator" OR FNO`
3. `DeepONet OR "deep operator network"`
4. `"physics-informed neural" AND operator`
5. `"operator learning" AND PDE`

All normalized to `PaperInfo` dataclass with source tag.

## Distributed Design (Multi-Worker)

- Spider output → Python Queue → 3 Downloader workers run in parallel
- worker 1: arxiv PDF download
- worker 2: pymupdf4llm conversion
- worker 3: GitHub code repo check
- Workers non-blocking, decoupled via shared queue

## Budget Control

- Filter TOP 20 papers (no duplicates)
- PDF download + conversion only (local CPU, 0 tokens)
- Abstract analysis + code check only (control LLM tokens)
- Target: ≤ ¥20 (~$3 USD)

## Timeline

- 0-5min: Scrapy crawl + dedup → candidate list
- 5-30min: Parallel PDF download (3 workers)
- 30-45min: pymupdf4llm conversion
- 45-60min: Code repo check (requests + web scraping)
- 60-90min: Analysis + wiki write
