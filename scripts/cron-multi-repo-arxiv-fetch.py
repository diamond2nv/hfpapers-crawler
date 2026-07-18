#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
multi-repo-arxiv-fetch.py — 多领域 arXiv 每日采集 (0-token, standalone)

三领域:
  - fusion (fusion-tech-intelligence)
  - coc    (coc-inverse-agent)
  - gsnv   (gsnv-theory)

输出:
  ~/.hermes/data/arxiv-live/arxiv-all.jsonl   — 共享主库
  ~/.hermes/data/arxiv-live/arxiv-new.jsonl   — 本轮新增
  <各repo>/data/live/arxiv-all.jsonl          — repo本地副本
  <各repo>/data/live/arxiv-new.jsonl          — repo本地副本

每条带 repo 标记: {"arxiv_id": "...", "repo": "fusion|coc|gsnv", ...}

Usage:
    python ~/.hermes/scripts/multi-repo-arxiv-fetch.py
    python ~/.hermes/scripts/multi-repo-arxiv-fetch.py --days 7
    python ~/.hermes/scripts/multi-repo-arxiv-fetch.py --quiet
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────
# TEMPLATE: Customize these paths for your Hermes setup
# Override via env vars: HFPCLAWER_DATA_DIR, HERMES_SCRIPTS_DIR

SHARED_DIR = Path(os.environ.get(
    "HFPCLAWER_DATA_DIR",
    str(Path.home() / ".hermes" / "data" / "arxiv-live")
))
SHARED_DIR = Path(SHARED_DIR)
SHARED_DIR.mkdir(parents=True, exist_ok=True)

ALL_PATH = SHARED_DIR / "arxiv-all.jsonl"
NEW_PATH = SHARED_DIR / "arxiv-new.jsonl"

REPO_MAP = {}
_repos_env = os.environ.get("HFPCLAWER_REPO_MAP")
if _repos_env:
    for pair in _repos_env.split(","):
        if "=" in pair:
            name, path = pair.split("=", 1)
            REPO_MAP[name.strip()] = Path(path.strip())
else:
    REPO_MAP = {
        "fusion": Path.home() / "Documents/Gitlab/forgejo-self-host/fusion-tech-intelligence",
        "coc":    Path.home() / "Documents/Gitlab/forgejo-self-host/coc-inverse-agent",
        "gsnv":   Path.home() / "Documents/Gitlab/forgejo-self-host/gsnv-theory",
    }

ARXIV_API = "https://export.arxiv.org/api/query"

# ── Domain Queries ───────────────────────────────────

DOMAINS = {
    "fusion": {
        "label": "核聚变",
        "queries": [
            'all:"nuclear fusion"',
            'all:"tokamak" AND all:plasma',
            'all:"stellarator" AND all:fusion',
            'all:"magnetic confinement" AND all:fusion',
            'all:"fusion reactor" AND all:design',
            'all:"REBCO" AND all:"fusion"',
            'all:"HTS" AND all:"fusion"',
            'cat:physics.plasm-ph AND all:fusion',
            'all:"fusion energy" AND all:economics',
            'all:"AI" AND all:"plasma control"',
        ],
    },
    "coc": {
        "label": "腔光机械",
        "queries": [
            'all:"cavity optomechanics" AND all:silicon',
            'all:"optomechanical crystal" AND all:design',
            'all:"inverse design" AND (all:photon* OR all:optom*)',
            'all:"cavity optomechanics" AND (all:nonlinear OR all:quantum)',
            'all:"optomagnonics" OR all:"magnon-photon"',
            'all:"Brillouin" AND (all:optomechanics OR all:phononic)',
            'all:"topology optimization" AND (all:photonic OR all:phononic)',
            'cat:physics.optics AND all:"whispering gallery" AND all:sensor',
            'all:"nanophotonic" AND all:cavity AND all:mechanical',
            'all:"cavity magnomechanics"',
        ],
    },
    "gsnv": {
        "label": "钢轨NV检测",
        "queries": [
            'all:"NV center" AND all:magnetometry AND all:sensing',
            'all:"nitrogen-vacancy" AND all:diamond AND all:magnetic',
            'all:"magnetic flux leakage" AND (all:NDT OR all:inspection)',
            'all:"quantum diamond" AND all:microscopy',
            'all:"NV center" AND all:eddy current',
            'all:"rail crack" AND (all:detection OR all:NDT)',
            'all:"NV" AND all:steel AND all:magnetometry',
            'all:"diamond magnetometer" AND all:sensitivity',
            'all:"magnetic imaging" AND all:defect AND all:quantum',
            'all:"spin-strain" AND all:NV AND all:diamond',
        ],
    },
    "neural-pde": {
        "label": "神经算子PDE",
        "queries": [
            'all:"neural operator" AND all:PDE',
            'all:"Fourier neural operator" AND all:solver',
            'all:"DeepONet" OR all:"physics-informed neural operator"',
            'all:"operator learning" AND all:"partial differential equation"',
            'cat:cs.LG AND all:"physics-informed" AND all:diffusion',
            'all:"scientific machine learning" AND all:PDE',
            'all:"graph neural" AND all:PDE AND all:solver',
            'all:"transformer" AND all:PDE AND all:solver',
            'all:"physics-informed diffusion" AND all:generation',
            'all:"PDE surrogate" AND (all:diffusion OR all:score)',
        ],
    },
}

# ── Fetch ────────────────────────────────────────────


def fetch_arxiv(query: str, max_results: int = 10) -> list[dict]:
    """Fetch papers from arXiv API. Returns [] on failure/timeout."""
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "MultiRepoArxivFetch/1.0 (hermes-agent)"
    })

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml_data = resp.read().decode("utf-8")
    except Exception as e:
        print(f"  ⚠️  arXiv API error: {e}", file=sys.stderr)
        return []

    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(xml_data)
    papers = []

    for entry in root.findall("a:entry", ns):
        paper_id = entry.find("a:id", ns).text.strip() if entry.find("a:id", ns) is not None else ""
        arxiv_id_match = re.search(r"/(\d+\.\d+)(?:v\d+)?", paper_id)
        arxiv_id = arxiv_id_match.group(1) if arxiv_id_match else paper_id.split("/")[-1]

        title = (
            entry.find("a:title", ns).text.strip().replace("\n", " ").replace("\r", "")
            if entry.find("a:title", ns) is not None else ""
        )
        summary = (
            entry.find("a:summary", ns).text.strip().replace("\n", " ").replace("\r", "")[:500]
            if entry.find("a:summary", ns) is not None else ""
        )
        published = (
            entry.find("a:published", ns).text.strip()
            if entry.find("a:published", ns) is not None else ""
        )
        updated = (
            entry.find("a:updated", ns).text.strip()
            if entry.find("a:updated", ns) is not None else ""
        )

        author_names = []
        for author in entry.findall("a:author", ns):
            name_el = author.find("a:name", ns)
            if name_el is not None:
                author_names.append(name_el.text.strip())

        categories = []
        for cat in entry.findall("a:category", ns):
            term = cat.get("term", "")
            if term:
                categories.append(term)

        links = {}
        for link in entry.findall("a:link", ns):
            rel = link.get("rel", "alternate")
            href = link.get("href", "")
            if rel == "alternate" and "pdf" in href:
                links["pdf"] = href

        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "authors": author_names[:5],
            "author_count": len(author_names),
            "summary": summary,
            "published": published,
            "updated": updated,
            "categories": categories[:5],
            "links": links,
            "source_query": query[:60],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })

    return papers


def load_existing_ids(jsonl_path: Path) -> set:
    """Load existing arXiv IDs from JSONL to avoid duplicates."""
    if not jsonl_path.exists():
        return set()
    ids = set()
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                ids.add(data.get("arxiv_id", ""))
            except json.JSONDecodeError:
                continue
    return ids


def save_papers(papers: list[dict], jsonl_path: Path):
    """Append papers to JSONL."""
    with open(jsonl_path, "a", encoding="utf-8") as f:
        for p in papers:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")


def copy_to_repo(repo_name: str, repo_root: Path):
    """Copy shared JSONL to repo's data/live/ (creates dir if missing)."""
    live_dir = repo_root / "data" / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    for fname in ["arxiv-all.jsonl", "arxiv-new.jsonl"]:
        src = SHARED_DIR / fname
        if src.exists():
            dst = live_dir / fname
            shutil.copy2(str(src), str(dst))


def main():
    parser = argparse.ArgumentParser(description="多领域 arXiv 每日采集")
    parser.add_argument("--days", type=int, default=7, help="搜索多少天内的新论文 (default: 7)")
    parser.add_argument("--quiet", action="store_true", help="安静模式，仅输出计数")
    parser.add_argument("--max-per-query", type=int, default=10, help="每查询返回最大数 (default: 10)")
    parser.add_argument("--domain", type=str, default="", help="仅指定领域: fusion|coc|gsnv (默认全跑)")
    args = parser.parse_args()

    # Filter domains
    domains_to_run = DOMAINS
    if args.domain:
        if args.domain in DOMAINS:
            domains_to_run = {args.domain: DOMAINS[args.domain]}
        else:
            print(f"[ERR] 未知领域: {args.domain}，可选: {list(DOMAINS.keys())}", file=sys.stderr)
            return 1

    if not args.quiet:
        domain_labels = ", ".join(d["label"] for d in DOMAINS.values())
        print(f"📡 多领域 arXiv 采集 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"   领域: {domain_labels}")
        print(f"   过去 {args.days} 天, 每查询 {args.max_per_query} 条")

    # Load existing IDs
    existing_ids = load_existing_ids(ALL_PATH)
    if not args.quiet:
        print(f"   已有论文: {len(existing_ids)} 篇")

    all_new = []
    total_queries = sum(len(d["queries"]) for d in domains_to_run.values())
    query_idx = 0
    MAX_TOTAL_TIME = 90  # seconds (cron no_agent timeout is 120s, leave margin)
    t_start = time.time()

    for repo_key, domain in domains_to_run.items():
        for query in domain["queries"]:
            query_idx += 1
            elapsed = time.time() - t_start
            if elapsed > MAX_TOTAL_TIME:
                if not args.quiet:
                    print(f"   ⏱️  超时预算 ({MAX_TOTAL_TIME}s)，跳过剩余 {total_queries - query_idx + 1} 个查询")
                break

            # Rate limit: 1 req / 3s rolling (arXiv API limit)
            if query_idx > 1:
                time.sleep(3.0)

            papers = fetch_arxiv(query, max_results=args.max_per_query)
            if not papers:
                continue

            # Oldest-first for dedup
            papers = list(reversed(papers))
            new_papers = []
            for p in papers:
                if p["arxiv_id"] not in existing_ids:
                    p["repo"] = repo_key
                    new_papers.append(p)
                    existing_ids.add(p["arxiv_id"])

            if new_papers:
                all_new.extend(new_papers)

            if not args.quiet:
                print(
                    f"   [{query_idx:2d}/{total_queries}] [{repo_key:6s}] {query[:38]:38s} → {len(papers):2d} papers, {len(new_papers):2d} new"
                )

        if elapsed > MAX_TOTAL_TIME:
            break

    # Dedup by arxiv_id (keep first occurrence per repo priority)
    seen = {}
    for p in all_new:
        if p["arxiv_id"] not in seen:
            seen[p["arxiv_id"]] = p
    all_new = list(seen.values())

    # Sort by date (newest first)
    all_new.sort(key=lambda p: p.get("published", ""), reverse=True)

    # Save to shared location
    if all_new:
        save_papers(all_new, ALL_PATH)
        with open(NEW_PATH, "w", encoding="utf-8") as f:
            for p in all_new:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")

    # Copy to each repo's data/live/
    for repo_name, repo_root in REPO_MAP.items():
        if repo_root.exists():
            copy_to_repo(repo_name, repo_root)

    # Summary
    if not args.quiet:
        by_repo = {}
        for p in all_new:
            r = p.get("repo", "unknown")
            by_repo[r] = by_repo.get(r, 0) + 1

        print(f"\n{'=' * 50}")
        print(f"✅ 本轮新增: {len(all_new)} 篇")
        for r, c in sorted(by_repo.items()):
            print(f"   {r:6s}: {c} 篇")
        print(f"   主库: {ALL_PATH}")
        if all_new:
            print("\n📄 最新论文:")
            for p in all_new[:5]:
                published = p.get("published", "?")[:10]
                cats = ", ".join(p.get("categories", [])[:3])
                repo = p.get("repo", "?")
                print(f"   [{published}] [{repo}] {p['title'][:80]}")
                print(f"     arXiv:{p['arxiv_id']}  [{cats}]")

    # stdout for cron (new paper count)
    print(f"##find {len(all_new)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
