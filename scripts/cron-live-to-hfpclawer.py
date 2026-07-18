#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arxiv-live-to-hfpclawer.py — 零token桥接：cron JSONL → hfpclawer paper_store

从 ~/.hermes/data/arxiv-live/arxiv-new.jsonl 读取每日采集的新论文，
导入 hfpclawer 的 SQLite paper_store，每条标记 source=cron:<repo>。

这样 hfpclawer 就能感知到 cron 每天搜到的新论文，无需重复调用 arXiv API。

Usage:
    python ~/.hermes/scripts/arxiv-live-to-hfpclawer.py
    python ~/.hermes/scripts/arxiv-live-to-hfpclawer.py --all    # 导入全部历史
    python ~/.hermes/scripts/arxiv-live-to-hfpclawer.py --quiet  # 静默模式

依赖:
    - hfpclawer (hfpapers) 包已安装
    - ~/.hermes/data/arxiv-live/arxiv-new.jsonl 存在

数据目录通过以下方式确定（优先级）:
    1. HFPAPERS_DATA_DIR 环境变量（推荐）
    2. 安装的 hfpclawer 包 config.yaml → paths.data_dir
    3. 当前目录下的 data/
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# ── Paths ────────────────────────────────────────────

SHARED_DIR = Path.home() / ".hermes" / "data" / "arxiv-live"
NEW_PATH = SHARED_DIR / "arxiv-new.jsonl"
ALL_PATH = SHARED_DIR / "arxiv-all.jsonl"

# hfpclawer version for audit trail
try:
    from hfpapers import __version__ as HFPCLAWER_VERSION
except ImportError:
    HFPCLAWER_VERSION = "unknown"

# 各领域基准相关性（与 hfpclawer 自己的 relevance 尺度对齐）
DOMAIN_RELEVANCE = {
    "fusion": 40,
    "coc":    60,
    "gsnv":   60,
    "neural-pde": 70,
}


def import_jsonl(jsonl_path: Path, quiet: bool = False, dry_run: bool = False) -> dict:
    """Import papers from JSONL into hfpclawer paper_store."""
    if not jsonl_path.exists():
        return {"total": 0, "new": 0, "existing": 0, "errors": 0, "by_repo": {}}

    # Lazy import hfpclawer — paper_store 通过 HFPAPERS_DATA_DIR / config 定位 DB
    try:
        from hfpapers.paper_store import ensure_paper
    except ImportError:
        print("[ERR] hfpclawer (hfpapers) 包未安装", file=sys.stderr)
        sys.exit(1)

    papers = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                papers.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    stats = {"total": len(papers), "new": 0, "existing": 0, "errors": 0, "by_repo": {}}

    for p in papers:
        arxiv_id = p.get("arxiv_id", "")
        if not arxiv_id:
            stats["errors"] += 1
            continue

        repo = p.get("repo", "unknown")
        relevance = DOMAIN_RELEVANCE.get(repo, 30)
        source_tag = f"cron:{repo}"
        title = p.get("title", "")
        abstract = p.get("summary", "")[:2000]
        published = p.get("published", "")[:4]  # year

        if dry_run:
            stats["by_repo"][repo] = stats["by_repo"].get(repo, 0) + 1
            continue

        try:
            sf_id, is_new = ensure_paper(
                arxiv_id=arxiv_id,
                title=title,
                source=source_tag,
                abstract=abstract,
                relevance=relevance,
                doi=p.get("doi", ""),
                skip_crossref=True,
                imported_via=f"hfpclawer@{HFPCLAWER_VERSION}",
            )
            if is_new:
                stats["new"] += 1
                stats["by_repo"][repo] = stats["by_repo"].get(repo, 0) + 1
            else:
                stats["existing"] += 1
        except Exception as e:
            stats["errors"] += 1
            if not quiet:
                print(f"  ⚠️  [{arxiv_id}] import failed: {e}", file=sys.stderr)

    return stats


def main():
    parser = argparse.ArgumentParser(description="cron JSONL → hfpclawer paper_store 桥接")
    parser.add_argument("--all", action="store_true", help="导入全部历史 (arxiv-all.jsonl)")
    parser.add_argument("--quiet", action="store_true", help="安静模式")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际写入")
    args = parser.parse_args()

    source_path = ALL_PATH if args.all else NEW_PATH
    label = "全部历史" if args.all else "本轮新增"

    if not source_path.exists():
        print(f"[WARN] {source_path} 不存在，跳过")
        return 0

    if args.dry_run:
        print(f"🔍 [DRY RUN] 将导入 {label} → hfpclawer paper_store")
        stats = import_jsonl(source_path, quiet=args.quiet, dry_run=True)
        print(f"   共 {stats['total']} 篇论文")
        for repo, count in sorted(stats["by_repo"].items()):
            print(f"   {repo:6s}: {count} 篇")
        print("   未实际写入 (--dry-run)")
        return 0

    t0 = time.time()
    if not args.quiet:
        print(f"📥 导入 {label} → hfpclawer paper_store...")

    stats = import_jsonl(source_path, quiet=args.quiet)

    elapsed = time.time() - t0
    if not args.quiet:
        print(f"\n{'=' * 45}")
        print(f"✅ 完成 ({elapsed:.1f}s)")
        print(f"   总计: {stats['total']} 篇")
        print(f"   新增: {stats['new']} 篇")
        print(f"   已存在: {stats['existing']} 篇")
        print(f"   错误: {stats['errors']} 篇")
        if stats["new"] > 0:
            print(f"\n  按 repo:")
            for repo, count in sorted(stats["by_repo"].items()):
                print(f"   {repo:6s}: {count} 篇 (relevance={DOMAIN_RELEVANCE.get(repo, 30)})")

    # stdout for cron
    print(f"##import {stats['new']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
