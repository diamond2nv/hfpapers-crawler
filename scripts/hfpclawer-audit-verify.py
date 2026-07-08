#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hfpclawer-audit-verify.py — 异步交叉审核 + 撤稿检测

用途: 对 cron 快速导入（skip_crossref=True）的论文做延迟批量的
      Crossref 交叉验证和 arXiv 撤稿检测。

用法:
  python3 hfpclawer-audit-verify.py                          # 审核所有未验证的 cron 论文
  python3 hfpclawer-audit-verify.py --since 2026-06-01        # 只审核某日期后入库的
  python3 hfpclawer-audit-verify.py --retraction-check        # 只做撤稿检测
  python3 hfpclawer-audit-verify.py --all                     # 强制全文再验证

输出: 审核结果写入 stdout + papers.verified / papers.verified_at 更新
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# ── Config ────────────────────────────────

HFPCLAWER_ROOT = os.path.expanduser(
    "~/Documents/Gitlab/Agentic4Sci/hfpapers-crawler"
)
os.chdir(HFPCLAWER_ROOT)
sys.path.insert(0, ".")

from hfpapers.paper_store import get_store, get_crossref
from hfpapers import __version__ as HFPCLAWER_VERSION


def batch_verify(store, cr, since: str = "", retraction_only: bool = False) -> dict:
    """Verify unverified papers in batch (rate-limited for Crossref API)."""
    stats = {"total": 0, "verified_new": 0, "already_verified": 0,
             "doi_found": 0, "venue_found": 0, "retractions": 0, "errors": 0}

    # 查询未验证的 cron 来源论文
    with store._conn() as conn:
        if since:
            rows = conn.execute(
                """SELECT p.* FROM papers p
                   WHERE p.source LIKE 'cron:%' AND p.created_at >= ?
                   ORDER BY p.created_at DESC""",
                (since,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT p.* FROM papers p
                   WHERE p.source LIKE 'cron:%' AND p.verified = 0
                   ORDER BY p.created_at DESC LIMIT 500""",
            ).fetchall()
    stats["total"] = len(rows)

    for row in rows:
        sf_id = row["sf_id"]
        arxiv_id = None
        title = row["title"]

        # 获取 arxiv ID
        ids = store.get_identifiers(sf_id)
        for id_rec in ids:
            if id_rec.id_type == "arxiv":
                arxiv_id = id_rec.id_value
                break

        if not arxiv_id or not title:
            continue

        # ── 撤稿检测：arXiv API 查询论文状态 ──
        if retraction_only or not retraction_only:
            try:
                import urllib.request
                import xml.etree.ElementTree as ET

                url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}&max_results=1"
                req = urllib.request.urlopen(url, timeout=10)
                xml_data = req.read().decode("utf-8")
                root = ET.fromstring(xml_data)
                ns = {"a": "http://www.w3.org/2005/Atom"}

                entries = root.findall("a:entry", ns)
                if entries:
                    entry = entries[0]
                    # 检查 withdrawn (不存在于标准 Atom, arXiv 用 title 前缀标记)
                    title_el = entry.find("a:title", ns)
                    fresh_title = title_el.text.strip().replace("\n", " ") if title_el is not None and title_el.text else ""

                    if fresh_title.startswith("WITHDRAWN"):
                        stats["retractions"] += 1
                        print(f"  ⚠️  RETRACTED: [{arxiv_id}] {fresh_title[:60]}")
                        continue

                    if fresh_title and fresh_title != title[:len(fresh_title)]:
                        print(f"  ℹ️  TITLE CHANGED: [{arxiv_id}]")
                        print(f"     old: {title[:60]}")
                        print(f"     new: {fresh_title[:60]}")

            except Exception as e:
                stats["errors"] += 1
                print(f"  ⚠️  [{arxiv_id}] arXiv query failed: {e}")

        # ── Crossref 交叉验证 ──
        if not retraction_only:
            try:
                result = cr.cross_verify(arxiv_id, title)
            except Exception as e:
                stats["errors"] += 1
                print(f"  ⚠️  [{arxiv_id}] Crossref verify failed: {e}")
                continue

            if result and result.get("doi"):
                doi = result["doi"]
                store.add_identifier(
                    sf_id, "doi", doi,
                    source="crossref",
                    confidence=result["confidence"],
                )
                stats["doi_found"] += 1
                stats["verified_new"] += 1

                if result.get("venue"):
                    paper = store.get_paper_by_id(sf_id)
                    if paper and not paper.venue:
                        paper.venue = result["venue"]
                        paper.year = result.get("year", 0)
                        store.upsert_paper(paper)
                    stats["venue_found"] += 1

                # 标记为已验证
                store.verify_paper(sf_id)
            elif result and result.get("error") is None:
                # 查询返回了内容但没有 DOI → 仍标记为已验证（有 arXiv ID 但无 Crossref DOI 是正常的）
                store.verify_paper(sf_id)
                stats["verified_new"] += 1

        # Crossref API rate limit: 1 req/s
        time.sleep(1.1)

    return stats


def print_report(stats: dict, elapsed: float):
    print(f"\n{'=' * 45}")
    print(f"✅ 审核完成 ({elapsed:.1f}s)")
    print(f"   扫描论文:       {stats['total']}")
    print(f"   新增已验证:     {stats['verified_new']}")
    print(f"   DOI 匹配:       {stats['doi_found']}")
    print(f"   Venue 补全:     {stats['venue_found']}")
    print(f"   撤稿/异常:      {stats['retractions']}")
    print(f"   错误:           {stats['errors']}")


def main():
    parser = argparse.ArgumentParser(description="hfpclawer 异步交叉审核 + 撤稿检测")
    parser.add_argument("--since", help="只审核某日期后入库的 (YYYY-MM-DD)")
    parser.add_argument("--retraction-check", action="store_true", help="只做撤稿检测，跳过 Crossref")
    parser.add_argument("--all", action="store_true", help="强制全文再验证")
    args = parser.parse_args()

    store = get_store()
    cr = get_crossref()

    t0 = time.time()

    if args.all:
        # 全部重新验证
        with store._conn() as conn:
            rows = conn.execute(
                "SELECT sf_id FROM papers WHERE source LIKE 'cron:%'"
            ).fetchall()
        stats = {"total": len(rows), "verified_new": 0, "already_verified": 0,
                 "doi_found": 0, "venue_found": 0, "retractions": 0, "errors": 0}
        for row in rows:
            sf_id = row["sf_id"]
            ids = store.get_identifiers(sf_id)
            paper = store.get_paper_by_id(sf_id)
            arxiv_id = next((i.id_value for i in ids if i.id_type == "arxiv"), None)
            if not arxiv_id or not paper:
                continue
            try:
                result = cr.cross_verify(arxiv_id, paper.title)
                if result and result.get("doi"):
                    store.add_identifier(sf_id, "doi", result["doi"],
                                         source="crossref", confidence=result["confidence"])
                    store.verify_paper(sf_id)
                    stats["verified_new"] += 1
                time.sleep(1.1)
            except Exception:
                stats["errors"] += 1
        print_report(stats, time.time() - t0)
        return 0

    stats = batch_verify(store, cr, since=args.since,
                         retraction_only=args.retraction_check)
    print_report(stats, time.time() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
