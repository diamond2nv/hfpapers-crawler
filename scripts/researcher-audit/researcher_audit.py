#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
researcher_audit.py — 研究者论文审计管线

按 YAML 配置的研究人员清单，步进扫描近8年论文列表，交叉校验：
  ① Semantic Scholar API → 论文元数据 (title, year, venue, arXiv ID, DOI)
  ② hfpclawer Zotero local API → 是否已在 Zotero、是否有 PDF 附件
  ③ 输出 JSONL + 控制台统计摘要

用法:
  cd ~/Documents/Gitlab/Agentic4Sci/hfpapers-crawler
  uv run python scripts/researcher-audit/researcher_audit.py \
      --config scripts/researcher-audit/people.yaml \
      --output scripts/researcher-audit/audit.jsonl

依赖:
  pip install requests    # Semantic Scholar API
  pyzotero               # Zotero local API (hfpclawer 已有)
  PyYAML                 # YAML 配置
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("researcher_audit")

# ─── Constants ───────────────────────────────────────
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1"
S2_HEADERS = {"User-Agent": "hfpclawer-researcher-audit/1.0"}
ARXIV_API = "http://export.arxiv.org/api/query"

# 每次 API 调用的间隔 (秒)，避免限流
API_DELAY = 0.5


# ─── Data models ─────────────────────────────────────

@dataclass
class Researcher:
    """A single researcher profile from YAML config."""
    name_cn: str
    name_en: str
    affiliation: str
    google_scholar_id: str = ""
    orcid: str = ""
    since_year: int = 2018
    max_papers: int = 100
    keywords: list[str] = field(default_factory=list)


@dataclass
class PaperRecord:
    """Audit result for a single paper."""
    researcher: str                           # e.g. "董春华"
    researcher_en: str                        # e.g. "Chun-Hua Dong"
    title: str
    year: int
    venue: str = ""
    arxiv_id: str = ""
    doi: str = ""
    authors: list[str] = field(default_factory=list)
    s2_paper_id: str = ""                     # Semantic Scholar paper ID
    # Zotero cross-check
    in_zotero: bool = False
    zotero_key: str = ""
    has_pdf: bool = False
    pdf_path: str = ""
    has_notes: bool = False
    note_count: int = 0
    # Metadata
    checked_at: str = ""
    source: str = "semantic-scholar"
    error: str = ""


# ─── Semantic Scholar API ────────────────────────────

def _s2_get(path: str, params: dict | None = None, retries: int = 3) -> dict:
    """GET Semantic Scholar API with retry and 429 backoff."""
    url = f"{SEMANTIC_SCHOLAR_API}{path}"
    for attempt in range(retries + 1):
        try:
            if params:
                qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
                url_full = f"{url}?{qs}"
            else:
                url_full = url
            req = urllib.request.Request(url_full, headers=S2_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 5 * (2 ** attempt)  # 5, 10, 20s
                logger.warning("  S2 429 rate limited, waiting %ds (attempt %d/%d)...", wait, attempt + 1, retries)
                time.sleep(wait)
                continue
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            return {"error": str(e)}
        except (urllib.error.URLError, OSError) as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            return {"error": str(e)}
        except json.JSONDecodeError as e:
            return {"error": f"JSON decode: {e}"}
    return {"error": "max retries exceeded"}


def search_author_id(name_en: str, affiliation: str = "") -> list[dict]:
    """Search Semantic Scholar for an author by name.

    Returns list of author matches, each with:
      {authorId, name, affiliations, paperCount, citationCount, hIndex}
    """
    params: dict[str, Any] = {
        "query": name_en,
        "limit": 10,
        "fields": "authorId,name,affiliations,paperCount,citationCount,hIndex",
    }
    data = _s2_get("/author/search", params=params)
    if "error" in data:
        logger.warning("  S2 search failed: %s", data["error"])
        return []

    results = []
    for hit in data.get("data", []):
        affils = [a.lower() for a in (hit.get("affiliations") or [])]
        affil_ok = not affiliation or any(affiliation.lower()[:10] in a for a in affils)
        name_ok = name_en.lower().split(",")[0].strip() in hit.get("name", "").lower()
        if affil_ok or name_ok:
            results.append(hit)
    return results


def get_author_papers(
    author_id: str,
    since_year: int = 2018,
    max_papers: int = 100,
    fields: str = "title,year,venue,externalIds,authors,authors.name",
) -> list[dict]:
    """Get an author's papers from Semantic Scholar.

    Returns list of paper dicts, filtered by year >= since_year.
    """
    papers: list[dict] = []
    offset = 0
    limit = 100  # S2 max per page

    while len(papers) < max_papers:
        params: dict[str, Any] = {
            "limit": min(limit, max_papers - len(papers)),
            "offset": offset,
            "fields": fields,
        }
        data = _s2_get(f"/author/{author_id}/papers", params=params)
        if "error" in data:
            logger.warning("  S2 papers failed: %s", data["error"])
            break

        batch = data.get("data", [])
        if not batch:
            break

        for p in batch:
            year = (p.get("year") or 0)
            if isinstance(year, int) and year >= since_year:
                papers.append(p)

        offset += len(batch)
        if len(batch) < limit:
            break
        time.sleep(API_DELAY)

    return papers[:max_papers]


def parse_s2_paper(paper: dict, researcher: Researcher) -> PaperRecord:
    """Convert a Semantic Scholar paper dict to PaperRecord."""
    external_ids = paper.get("externalIds") or {}
    arxiv_id = external_ids.get("Arxiv", "")
    doi = external_ids.get("DOI", "")

    # Normalize arXiv ID
    if arxiv_id:
        arxiv_id = arxiv_id.replace("arXiv:", "").strip()

    authors = [a.get("name", "") for a in (paper.get("authors") or [])]

    return PaperRecord(
        researcher=researcher.name_cn,
        researcher_en=researcher.name_en,
        title=(paper.get("title") or ""),
        year=(paper.get("year") or 0),
        venue=(paper.get("venue") or ""),
        arxiv_id=arxiv_id,
        doi=doi,
        authors=authors,
        s2_paper_id=paper.get("paperId", ""),
        checked_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


# ─── Zotero cross-check ──────────────────────────────

def check_zotero(record: PaperRecord) -> PaperRecord:
    """Cross-check a paper record against Zotero local API.

    Uses hfpclawer's ZoteroClient (pyzotero-based, localhost:23119).

    Steps:
      1. Search by arXiv ID (most reliable)
      2. Fallback: search by DOI
      3. If found: check children for PDF attachment + notes
    """
    try:
        from hfpclawer.zotero import ZoteroClient
        zc = ZoteroClient()
    except ImportError:
        record.error = "pyzotero not installed"
        return record
    except Exception as e:
        record.error = f"Zotero connect: {e}"
        return record

    # Step 1: try arXiv ID
    item_key = None
    if record.arxiv_id:
        try:
            item_key = zc.is_arxiv_in_zotero(record.arxiv_id)
        except Exception:
            pass

    # Step 2: fallback to DOI
    if not item_key and record.doi:
        try:
            match = zc.search_by_doi(record.doi)
            if match:
                item_key = match.get("data", {}).get("key", "")
        except Exception:
            pass

    if not item_key:
        return record  # not in Zotero

    record.in_zotero = True
    record.zotero_key = item_key

    # Step 3: check children for PDF + notes
    try:
        children = zc.get_children(item_key)
        for child in children:
            cdata = child.get("data", {})
            item_type = cdata.get("itemType", "")
            if item_type == "attachment":
                ct = cdata.get("contentType", "")
                fn = (cdata.get("filename") or "").lower()
                if ct == "application/pdf" or fn.endswith(".pdf"):
                    record.has_pdf = True
                    # Try to resolve local path
                    try:
                        from hfpclawer.zotero.annotations import resolve_pdf_path
                        info = resolve_pdf_path(zotero_key=item_key)
                        if "pdf_path" in info and info["pdf_path"]:
                            record.pdf_path = info["pdf_path"]
                    except Exception:
                        pass
            elif item_type == "note":
                record.has_notes = True
                record.note_count += 1
    except Exception as e:
        record.error = f"children: {e}"

    return record


# ─── arXiv API fallback (for papers without arXiv ID in S2) ──

def fetch_arxiv_id(record: PaperRecord) -> str:
    """Try to find arXiv ID from arXiv API by title search."""
    if record.arxiv_id:
        return record.arxiv_id
    if not record.title:
        return ""

    import urllib.parse
    import xml.etree.ElementTree as ET

    ctx = __import__("ssl")._create_unverified_context()
    try:
        title_q = urllib.parse.quote(record.title[:200])
        url = f"{ARXIV_API}?search_query=ti:{title_q}&max_results=3&sortBy=relevance"
        req = urllib.request.Request(url, headers={"User-Agent": "hfpclawer/1.0"})
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        ns = {"a": "http://www.w3.org/2005/Atom"}

        for entry in root.findall("a:entry", ns):
            title_el = entry.find("a:title", ns)
            if title_el is not None and title_el.text:
                found_title = " ".join(title_el.text.split())
                # Simple title match
                if record.title.lower()[:30] in found_title.lower():
                    id_el = entry.find("a:id", ns)
                    if id_el is not None and id_el.text:
                        aid = id_el.text.strip().split("/abs/")[-1].split("v")[0]
                        return aid
    except Exception:
        pass
    return ""


# ─── Main pipeline ───────────────────────────────────

def load_config(path: str | Path) -> list[Researcher]:
    """Load researcher list from YAML config."""
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    researchers = []
    for r in cfg.get("researchers", []):
        researchers.append(Researcher(
            name_cn=r.get("name_cn", ""),
            name_en=r.get("name_en", ""),
            affiliation=r.get("affiliation", ""),
            google_scholar_id=r.get("google_scholar_id", ""),
            orcid=r.get("orcid", ""),
            since_year=r.get("since_year", 2018),
            max_papers=r.get("max_papers", 100),
            keywords=r.get("keywords", []),
        ))
    return researchers


def audit_researcher(
    researcher: Researcher,
    skip_zotero: bool = False,
) -> list[PaperRecord]:
    """Audit a single researcher: fetch papers + cross-check Zotero."""
    cn = researcher.name_cn
    en = researcher.name_en
    logger.info("=" * 60)
    logger.info("📋 研究者: %s (%s)", cn, en)
    if researcher.orcid:
        logger.info("   ORCID: %s", researcher.orcid)
    logger.info("   扫描范围: %d–%s", researcher.since_year, datetime.now().year)
    logger.info("")

    # Step 1: find Semantic Scholar author ID
    logger.info("  [1/3] 搜索 Semantic Scholar 作者 ID...")
    matches = search_author_id(en, researcher.affiliation)
    if not matches:
        logger.warning("  ⚠️  未在 Semantic Scholar 找到作者: %s", en)
        return []

    author = matches[0]
    author_id = author.get("authorId", "")
    logger.info("  ✅ 找到: %s (authorId=%s, %d papers, h-index=%s)",
                author.get("name", "?"),
                author_id,
                author.get("paperCount", "?"),
                author.get("hIndex", "?"))
    time.sleep(API_DELAY)

    # Step 2: fetch papers
    logger.info("  [2/3] 获取论文列表 (since %d)...", researcher.since_year)
    s2_papers = get_author_papers(author_id, researcher.since_year, researcher.max_papers)
    logger.info("  ✅ 获取 %d 篇论文 (since %d)", len(s2_papers), researcher.since_year)
    time.sleep(API_DELAY)

    # Parse + arXiv fallback
    records: list[PaperRecord] = []
    for i, sp in enumerate(s2_papers):
        rec = parse_s2_paper(sp, researcher)
        # ArXiv API fallback for missing arXiv ID
        if not rec.arxiv_id:
            aid = fetch_arxiv_id(rec)
            if aid:
                rec.arxiv_id = aid
        records.append(rec)

        if (i + 1) % 20 == 0:
            logger.info("    解析 %d/%d...", i + 1, len(s2_papers))
        time.sleep(API_DELAY / 5)

    # Step 3: cross-check Zotero
    if not skip_zotero:
        logger.info("  [3/3] 交叉校验 Zotero...")
        for i, rec in enumerate(records):
            check_zotero(rec)
            if (i + 1) % 10 == 0:
                n_in = sum(1 for r in records[:i + 1] if r.in_zotero)
                n_pdf = sum(1 for r in records[:i + 1] if r.has_pdf)
                logger.info("    校验 %d/%d: Zotero内=%d, 有PDF=%d",
                            i + 1, len(records), n_in, n_pdf)
    else:
        logger.info("  [3/3] 跳过 Zotero 校验 (--skip-zotero)")

    return records


def print_summary(records: list[PaperRecord], researcher: Researcher) -> None:
    """Print a structured summary for one researcher."""
    total = len(records)
    if total == 0:
        print("")
        print("─" * 60)
        print(f"📊 {researcher.name_cn} ({researcher.name_en}) — 审计摘要")
        print("─" * 60)
        print(f"  论文总数:      0 (S2 无数据或 API 限流)")
        print("")
        return
    in_zotero = sum(1 for r in records if r.in_zotero)
    has_pdf = sum(1 for r in records if r.has_pdf)
    has_notes = sum(1 for r in records if r.has_notes)
    has_arxiv = sum(1 for r in records if r.arxiv_id)
    has_doi = sum(1 for r in records if r.doi)

    print("")
    print("─" * 60)
    print(f"📊 {researcher.name_cn} ({researcher.name_en}) — 审计摘要")
    print("─" * 60)
    print(f"  论文总数:      {total}")
    print(f"  含 arXiv ID:   {has_arxiv} ({has_arxiv/total*100:.0f}%)")
    print(f"  含 DOI:        {has_doi} ({has_doi/total*100:.0f}%)")
    print(f"  已在 Zotero:   {in_zotero} ({in_zotero/total*100:.0f}%)")
    print(f"  有 PDF 附件:   {has_pdf} ({has_pdf/total*100:.0f}%)")
    print(f"  有 Zotero 笔记: {has_notes}")
    print("")

    # 缺失统计
    missing = [r for r in records if not r.in_zotero]
    if missing:
        print(f"  ⚠️  Zotero 缺失 {len(missing)} 篇:")
        for r in missing[:15]:
            aid = f" [{r.arxiv_id}]" if r.arxiv_id else ""
            doi = f" DOI:{r.doi[:30]}" if r.doi else ""
            print(f"    · {r.year} {r.title[:70]}...{aid}{doi}")
        if len(missing) > 15:
            print(f"    ... 还有 {len(missing)-15} 篇")

    # PDF 缺失统计
    no_pdf = [r for r in records if r.in_zotero and not r.has_pdf]
    if no_pdf:
        print(f"  ⚠️  Zotero 内有但无 PDF 附件 {len(no_pdf)} 篇:")
        for r in no_pdf[:10]:
            print(f"    · {r.year} {r.title[:70]}...")
        if len(no_pdf) > 10:
            print(f"    ... 还有 {len(no_pdf)-10} 篇")

    print("")


# ─── CLI entry point ─────────────────────────────────

def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="研究者论文审计: Semantic Scholar → Zotero 交叉校验"
    )
    parser.add_argument("--config", default="scripts/researcher-audit/people.yaml",
                        help="YAML 配置文件路径")
    parser.add_argument("--output", default="scripts/researcher-audit/audit.jsonl",
                        help="JSONL 输出文件路径")
    parser.add_argument("--skip-zotero", action="store_true",
                        help="跳过 Zotero 交叉校验 (仅获取论文列表)")
    parser.add_argument("--researcher", default="",
                        help="限单个研究者 (name_cn 匹配)")
    parser.add_argument("--since", type=int, default=0,
                        help="覆盖 since_year (默认使用 YAML 配置)")
    args = parser.parse_args()

    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error("❌ 配置文件不存在: %s", config_path)
        sys.exit(1)

    researchers = load_config(config_path)
    if not researchers:
        logger.error("❌ 配置文件中无 researcher 条目")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("🔬 研究者论文审计管线启动")
    logger.info("   配置: %s", config_path)
    logger.info("   输出: %s", args.output)
    logger.info("   研究者: %d 人", len(researchers))
    logger.info("")

    all_records: list[PaperRecord] = []

    for researcher in researchers:
        # Filter by name
        if args.researcher and args.researcher not in researcher.name_cn and args.researcher not in researcher.name_en:
            continue

        # Override since_year
        if args.since > 0:
            researcher.since_year = args.since

        records = audit_researcher(researcher, skip_zotero=args.skip_zotero)
        all_records.extend(records)

        print_summary(records, researcher)

    # Write JSONL
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")

    # Grand summary
    total = len(all_records)
    in_zotero = sum(1 for r in all_records if r.in_zotero)
    has_pdf = sum(1 for r in all_records if r.has_pdf)
    logger.info("")
    logger.info("=" * 60)
    logger.info("🏁 审计完成")
    logger.info("   总论文: %d 篇", total)
    logger.info("   Zotero 内: %d 篇 (%d%%)", in_zotero, in_zotero * 100 // total if total else 0)
    logger.info("   有 PDF: %d 篇", has_pdf)
    logger.info("   输出: %s", output_path)
    logger.info("=" * 60)


if __name__ == "__main__":
    import urllib.parse  # needed for import at module scope
    main()
