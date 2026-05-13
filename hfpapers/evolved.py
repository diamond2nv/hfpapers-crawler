#!/usr/bin/env python3
# hfpapers/evolved.py — Crawler core engine (paper_store integrated)
# v3.3: Multi-source concurrent search via SearchDispatcher + AsyncPdfDownloader

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from hfpapers.config import get as cfg_get
from hfpapers.config import load_config
from hfpapers.hardware import HardwareProbe
from hfpapers.paper_store import ensure_paper, get_store

logger = logging.getLogger("hfpapers.evolved")

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / cfg_get("paths.data_dir", "data")
PDF_DIR = BASE_DIR / cfg_get("paths.pdf_dir", "pdfs")
MD_DIR = BASE_DIR / cfg_get("paths.md_dir", "mds")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PDF_DIR, exist_ok=True)
os.makedirs(MD_DIR, exist_ok=True)

# ════════════════════════════════════════════
# Data Model
# ════════════════════════════════════════════


@dataclass
class PaperInfo:
    arxiv_id: str = ""
    title: str = ""
    abstract: str = ""
    source_url: str = ""
    categories: list[str] = field(default_factory=list)
    relevance: int = 0
    code_url: str = ""
    has_code: str = "unknown"
    md5_abstract: str = ""


# ════════════════════════════════════════════
# Dedup Engine (paper_store adapter)
# ════════════════════════════════════════════


class DedupEngine:
    """Dedup Engine — based on paper_store (SQLite)

    Compatible with legacy interface: is_duplicate(), add(), count
    Actually uses ensure_paper() for dedup and cross-validation
    """

    def __init__(self):
        self._store = get_store()
        self.count = self._store.stats()["papers_total"]

    def is_duplicate(self, paper: PaperInfo) -> Optional[str]:
        existing = self._store.get_paper_by_identifier("arxiv", paper.arxiv_id)
        if existing:
            return f"arxiv_id={paper.arxiv_id}"
        return None

    def add(self, papers: list[PaperInfo]):
        """Batch write to paper_store"""
        for p in papers:
            ensure_paper(
                arxiv_id=p.arxiv_id,
                title=p.title,
                abstract=p.abstract,
                source="hfpapers.evolved",
                relevance=p.relevance,
                code_url=p.code_url,
            )
        self.count = self._store.stats()["papers_total"]

    def reload(self):
        self.count = self._store.stats()["papers_total"]


# ════════════════════════════════════════════
# Relevance Detector
# ════════════════════════════════════════════


class RelevanceDetector:
    def __init__(self):
        cfg = load_config()
        kw = cfg.get("keywords", {})
        self.include_high = kw.get("include_high", [])
        self.include_med = kw.get("include_medium", [])
        self.include_low = kw.get("include_low", [])
        self.exclude = kw.get("exclude", [])
        self.phrase_high = cfg.get("classification", {}).get("phrase_high", [])
        self.threshold_pass = cfg.get("classification", {}).get("threshold_pass", 30)

        hw = HardwareProbe()
        self.use_bert = hw.use_bert and cfg.get("classification", {}).get("bert_enabled", False)

    def classify(self, paper: PaperInfo) -> int:
        text = f"{paper.title}\n{paper.abstract}".lower()

        for kw in self.exclude:
            if kw in text:
                return 0

        score = self._keyword_score(text)
        if score >= 60:
            return score

        score = max(score, self._phrase_score(text))
        return min(score, 100)

    def _keyword_score(self, text: str) -> int:
        score = 0
        for kw in self.include_high:
            if kw in text:
                score += 20
        for kw in self.include_med:
            if kw in text:
                score += 10
        for kw in self.include_low:
            if kw in text:
                score += 5
        return min(score, 100)

    def _phrase_score(self, text: str) -> int:
        if not self.phrase_high:
            return 0
        score = 0
        for ph in self.phrase_high:
            if ph.lower() in text:
                score += 15
        return min(score, 80)


# ════════════════════════════════════════════
# Crawler Engine
# ════════════════════════════════════════════


class HFPapersCrawler:
    """Async Search Dispatcher — uses SearchDispatcher + AsyncPdfDownloader

    Supports:
    - Multi-source concurrent search (HF CLI, arXiv local/API, OpenReview)
    - arXiv title auto-verification
    - Deduplication
    - Relevance detection
    """

    def __init__(self, dedup: DedupEngine, detector: RelevanceDetector):
        self.dedup = dedup
        self.detector = detector
        self.found: list[PaperInfo] = []
        self.queries = cfg_get("search.queries", [])

    def crawl(self, max_pages: int = 3) -> list[PaperInfo]:
        """Search (sync interface, uses async dispatcher internally)

        Internally uses SearchDispatcher to search all dimensions concurrently.
        max_pages controls results per dimension (max_pages * 10).
        """
        import asyncio

        from hfpapers.search_queue import SearchDispatcher

        limit = max_pages * 10
        logger.info(f"🚀 Searching {len(self.queries)} dimensions, top-{limit}")

        # Use async dispatcher
        dispatcher = SearchDispatcher(max_workers=min(5, len(self.queries)))

        for q in self.queries:
            dispatcher.add_task(
                query=q.get("query", ""),
                category=q.get("category", "unknown"),
                limit=limit,
                priority=q.get("priority", 5),
            )

        # Run
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            search_results = loop.run_until_complete(dispatcher.run())
        finally:
            loop.close()

        # Relevance detection + paper_store dedup
        for sr in search_results:
            p = PaperInfo(
                arxiv_id=sr.arxiv_id,
                title=sr.title[:200],
                abstract=sr.abstract[:500],
                source_url=sr.source_url,
                categories=[sr.source_category],
                code_url=sr.code_url,
                md5_abstract=hashlib.md5(sr.abstract.encode()).hexdigest() if sr.abstract else "",
            )

            if self.dedup.is_duplicate(p):
                continue

            score = self.detector.classify(p)
            if score >= self.detector.threshold_pass:
                p.relevance = score
                self.found.append(p)
                logger.info(f"  ✅ {sr.arxiv_id} {sr.title[:60]} (rel={score})")

        logger.info(f"Search complete: {len(self.found)} new papers")
        return self.found


# ════════════════════════════════════════════
# Download + Convert
# ════════════════════════════════════════════


class PaperDownloader:
    """PDF Downloader (sync interface, uses AsyncPdfDownloader internally)"""

    def __init__(self, dedup: DedupEngine):
        self.dedup = dedup
        self.hw = HardwareProbe()

    def download_batch(self, papers: list[PaperInfo]):
        papers.sort(key=lambda p: p.relevance, reverse=True)
        total = len(papers)
        logger.info(f"📥 Downloading {total} PDFs ({min(8, total)} concurrent)...")

        from hfpapers.pdf_downloader_async import AsyncPdfDownloader

        async_dl = AsyncPdfDownloader(
            max_concurrent=min(8, total),
            progress_cb=lambda r: logger.info(
                f"  {'✅' if r['success'] else '❌'} {r['arxiv_id']}"
            ),
        )

        import asyncio
        papers_dict = [
            {"arxiv_id": p.arxiv_id, "title": p.title, "abstract": p.abstract}
            for p in papers
        ]

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(async_dl.download_batch(papers_dict))
        finally:
            loop.close()

        success = sum(1 for r in results if r["success"])
        logger.info(f"✅ Download complete: {success}/{total} successful")

        # Write to paper_store
        for p in papers:
            ensure_paper(
                arxiv_id=p.arxiv_id,
                title=p.title,
                abstract=p.abstract,
                source="downloader",
                relevance=p.relevance,
                code_url=p.code_url,
            )


# ════════════════════════════════════════════
# Candidate List Persistence
# ════════════════════════════════════════════


def save_candidates(papers) -> None:
    from datetime import datetime
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DATA_DIR / f"candidates_{now}.json"
    latest = DATA_DIR / "candidates_latest.json"
    data = [
        {
            "arxiv_id": p.arxiv_id,
            "title": p.title,
            "abstract": p.abstract,
            "source_url": p.source_url,
            "categories": p.categories,
            "relevance": p.relevance,
            "code_url": p.code_url,
            "has_code": p.has_code,
        }
        for p in papers
    ]
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    import shutil
    shutil.copy2(path, latest)
    logger.info(f"Candidate list saved: {path} ({len(papers)} papers)")
    print(f"💾 Candidate list: {path}")


def load_candidates() -> list:
    latest = DATA_DIR / "candidates_latest.json"
    if not latest.exists():
        return []
    with open(latest) as f:
        data = json.load(f)
    from hfpapers.evolved import PaperInfo
    papers = []
    for d in data:
        papers.append(PaperInfo(
            arxiv_id=d.get("arxiv_id", ""),
            title=d.get("title", ""),
            abstract=d.get("abstract", ""),
            source_url=d.get("source_url", ""),
            categories=d.get("categories", []),
            relevance=d.get("relevance", 0),
            code_url=d.get("code_url", ""),
            has_code=d.get("has_code", "unknown"),
        ))
    return papers


def convert_pdfs() -> int:
    count = 0
    for pdf_path in sorted(PDF_DIR.glob("*.pdf")):
        md_path = MD_DIR / pdf_path.with_suffix(".md").name
        if md_path.exists():
            count += 1
            continue
        try:
            import pymupdf4llm
            md_text = pymupdf4llm.to_markdown(str(pdf_path))
            aid = pdf_path.stem
            with open(md_path, "w") as fh:
                fh.write(f"# {aid}\n\n> arXiv PDF\n\n{md_text}")
            count += 1
            logger.info(f"  MD: {aid}")
        except Exception as e:
            logger.warning(f"  Conversion failed {pdf_path.name}: {e}")
    return count
