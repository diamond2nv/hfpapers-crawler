#!/usr/bin/env python3
"""AI4Math search - run all queries against arXiv API, save to paper_store + wiki."""
import json, os, sys, time, yaml
from pathlib import Path

BASE = Path(__file__).parent.parent
os.chdir(BASE)

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)
queries = cfg.get('search', {}).get('queries', [])
print(f'Loaded {len(queries)} queries', flush=True)

from hfpapers.searcher_registry import init_registry, get
init_registry()
arxiv = get('arxiv_api')

from hfpapers.evolved import PaperInfo, DedupEngine, RelevanceDetector
dedup = DedupEngine()
detector = RelevanceDetector()

all_papers = []
for i, q in enumerate(queries):
    query = q['query']
    cat = q.get('category', 'unknown')
    try:
        results = arxiv.search_sync(query, limit=20, category=cat)
        for sr in results:
            p = PaperInfo(
                arxiv_id=sr.arxiv_id,
                title=sr.title[:200],
                abstract=sr.abstract[:500],
                source_url=sr.source_url,
                categories=[sr.source_category],
                code_url=sr.code_url,
                doi=sr.doi,
            )
            if not dedup.is_duplicate(p):
                score = detector.classify(p)
                if score >= 30:
                    p.relevance = score
                    all_papers.append(p)
        print(f'[{i+1}/{len(queries)}] {cat}: {query[:40]} -> {len(results)} results', flush=True)
    except Exception as e:
        print(f'[{i+1}/{len(queries)}] FAIL {cat}: {query[:40]} -> {e}', flush=True)
    time.sleep(0.3)

print(f'\nTotal: {len(all_papers)} papers', flush=True)

# Save candidates
data_dir = Path('data')
candidates = []
for p in sorted(all_papers, key=lambda x: x.relevance, reverse=True):
    candidates.append({
        'arxiv_id': p.arxiv_id,
        'title': p.title,
        'abstract': p.abstract[:300],
        'relevance': p.relevance,
        'categories': p.categories,
        'source_url': p.source_url,
        'code_url': p.code_url,
        'doi': p.doi,
    })
with open(data_dir / 'candidates_latest.json', 'w') as f:
    json.dump(candidates, f, indent=2, ensure_ascii=False)
print(f'Candidates saved: {len(candidates)}', flush=True)

# Paper store
from hfpapers.paper_store import ensure_paper, store_stats
new_count = 0
for c in candidates:
    _, is_new = ensure_paper(
        arxiv_id=c['arxiv_id'],
        title=c['title'],
        source='arxiv_api',
        abstract=c.get('abstract', '')[:300],
        relevance=c.get('relevance', 0),
    )
    if is_new:
        new_count += 1
print(f'Paper store: {new_count} new papers', flush=True)

s = store_stats()
print(f'Store total: {s.get("papers_total", 0)} papers', flush=True)

# Category breakdown
by_cat = {}
for p in all_papers:
    cat = p.categories[0] if p.categories else 'unknown'
    by_cat.setdefault(cat, []).append(p)
print('\nBy category:')
for cat, papers in sorted(by_cat.items()):
    cnt = len(papers)
    print(f'  {cat}: {cnt}', flush=True)
    for p in papers[:5]:
        pid = p.arxiv_id
        t = p.title[:60]
        r = p.relevance
        print(f'    rel={r:3d} | {pid} | {t}', flush=True)
