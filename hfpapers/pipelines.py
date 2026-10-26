#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pipelines.py
"""
Pipeline Chain — each stage processes a PaperItem

Flow:
  0. Items enter
  1. StorePipeline — Write to paper_store (SQLite + Snowflake ID + Crossref cross-validation)
  2. ClassifyPipeline — Relevance classification (keyword/NLP)
  3. ExportPipeline — Export candidate list + update global dedup
  4. DownloadPipeline — PDF download + MD conversion
"""

import logging
import os
from datetime import datetime

from hfpapers.config import get as cfg_get
from hfpapers.config import load_config
from hfpapers.items import PaperItem
from hfpapers.paper_store import ensure_paper, get_store
from hfpapers.paths import pdf_dir as _default_pdf_dir
from hfpapers.paths import state_root

logger = logging.getLogger(__name__)


class StorePipeline:
    """Paper Store Pipeline — writes to SQLite unified storage layer

    Features:
      1. Uses ensure_paper() for dedup (arXiv ID deduplication)
      2. Auto-triggers Crossref cross-validation (title → DOI)
      3. Auto-verified via multi-identifier
      4. Returns sf_id for subsequent pipeline stages
    """

    def __init__(self):
        self.skipped = 0
        self.passed = 0
        #: sf_ids written by this run — the batch audits its own output at the end (v0.19.10).
        self.new_sf_ids: set[int] = set()

    def process_item(self, item: PaperItem, spider):
        arxiv_id = item.get("arxiv_id", "")
        if not arxiv_id:
            self.skipped += 1
            return None

        title = item.get("title", "")
        abstract = item.get("abstract", "")
        code_url = item.get("code_url", "")
        venue = item.get("venue", "")

        # Write to paper_store (dedup + cross-verify)
        sf_id, is_new = ensure_paper(
            arxiv_id=arxiv_id,
            title=title,
            abstract=abstract,
            source=item.get("source", "scrapy"),
            relevance=item.get("relevance_score", 0),
            venue=venue,
            code_url=code_url,
        )

        if not is_new:
            spider.logger.info(f"[STORE] Skipped (exists): {arxiv_id} {title[:40]}")
            self.skipped += 1
            return None

        # Write back sf_id for subsequent pipeline use
        item["sf_id"] = sf_id
        item["verified"] = True  # paper_store already verified
        self.passed += 1
        self.new_sf_ids.add(sf_id)
        return item

    def open_spider(self, spider):
        store = get_store()
        stats = store.stats()
        spider.logger.info(
            f"[STORE] Paper store: {stats['papers_total']} papers, {stats['papers_verified']} verified"
        )

    def close_spider(self, spider):
        logger.info(f"[STORE] This run: {self.passed} new, {self.skipped} skipped")
        self._report_new_records()

    def _report_new_records(self) -> None:
        """Check this run's own output now, instead of leaving it to the next audit (v0.19.10).

        The 2026-09-25 full audit found wrong DOIs that batch runs had written weeks earlier; nothing
        looked at a batch's output when the batch ran.  A tail check makes the defect a line in the
        run log — the moment it is created — rather than a surprise in a later report.
        """
        if not self.new_sf_ids:
            return
        from hfpapers.invariants import check_store

        report = check_store(get_store(), only_sf_ids=self.new_sf_ids)
        if not report.findings:
            logger.info(f"[STORE] health check: {len(self.new_sf_ids)} new record(s), 0 finding(s)")
            return
        logger.warning(
            f"[STORE] health check: {len(report.findings)} finding(s) among this run's "
            f"{len(self.new_sf_ids)} new record(s) — {report.by_check()}"
        )
        for finding in report.findings[:10]:
            logger.warning(f"[STORE]   {finding.check} · sf_id={finding.subject} · {finding.detail}")


class ClassifyPipeline:
    """Classification Pipeline — keyword/phrase graded scoring"""

    def __init__(self):
        cfg = load_config()
        kw = cfg.get("keywords", {})
        self.include_high = kw.get("include_high", [])
        self.include_med = kw.get("include_medium", [])
        self.include_low = kw.get("include_low", [])
        self.exclude = kw.get("exclude", [])
        self.phrase_high = cfg.get("classification", {}).get("phrase_high", [])
        self.threshold_pass = cfg.get("classification", {}).get("threshold_pass", 30)

    def process_item(self, item: PaperItem, spider):
        text = f"{item.get('title', '')}\n{item.get('abstract', '')}".lower()

        # Blacklist check
        for kw in self.exclude:
            if kw in text:
                spider.logger.info(f"[CLASSIFY] {item['arxiv_id']} blacklist hit: {kw}")
                return None

        score = self._keyword_score(text)
        score = max(score, self._phrase_score(text))
        score = min(score, 100)
        item["relevance_score"] = score

        if score >= self.threshold_pass:
            spider.logger.info(f"[CLASSIFY] {item['arxiv_id']} rel={score}")
            return item
        else:
            spider.logger.info(
                f"[CLASSIFY] {item['arxiv_id']} rel={score} below threshold {self.threshold_pass}"
            )
            return None

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


class ExportPipeline:
    """Export Pipeline — save candidate list + update paper_store

    This pipeline maintains:
      1. paper_store (SQLite) — primary storage
      2. candidates_latest.json — legacy JSON export
    """

    def __init__(self):
        self.candidates: list[dict] = []
        self.today = datetime.now().strftime("%Y-%m-%d")

    def process_item(self, item: PaperItem, spider):
        sf_id = item.get("sf_id", 0)
        arxiv_id = item.get("arxiv_id", "")
        title = item.get("title", "")
        abstract = item.get("abstract", "")
        relevance = item.get("relevance_score", 0)
        code_url = item.get("code_url", "")
        venue = item.get("venue", "")

        # Update paper_store relevance and code_url
        if sf_id:
            store = get_store()
            store.update_paper(sf_id, relevance=relevance, code_url=code_url)

        # JSON export cache
        self.candidates.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "abstract": abstract[:300],
                "relevance": relevance,
                "category": item.get("search_category", ""),
                "source": item.get("source", ""),
                "source_url": item.get("source_url", ""),
                "code_url": code_url,
                "venue": venue,
                "verified": item.get("verified", False),
            }
        )
        return item

    def close_spider(self, spider):
        if not self.candidates:
            logger.info("[EXPORT] No candidate papers")
            return

        # Sort by relevance
        self.candidates.sort(key=lambda x: x["relevance"], reverse=True)

        # Write JSON file (backward compatible)
        data_dir = os.path.join(
            str(state_root()), cfg_get("paths.data_dir", "data")
        )
        os.makedirs(data_dir, exist_ok=True)

        filepath = os.path.join(data_dir, f"candidates_{self.today}.json")
        with open(filepath, "w") as f:
            import json

            json.dump(self.candidates, f, indent=2, ensure_ascii=False)

        latest = os.path.join(data_dir, "candidates_latest.json")
        with open(latest, "w") as f:
            import json

            json.dump(self.candidates, f, indent=2, ensure_ascii=False)

        logger.info(f"[EXPORT] {len(self.candidates)} papers → {filepath} + paper_store")


class DownloadPipeline:
    """Download Pipeline — PDF download + MD conversion"""

    def __init__(self):
        import requests

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

        base = str(state_root())
        self.pdf_dir = str(cfg_get("paths.pdf_dir", str(_default_pdf_dir())))
        self.md_dir = os.path.join(base, cfg_get("paths.md_dir", "mds"))
        os.makedirs(self.pdf_dir, exist_ok=True)
        os.makedirs(self.md_dir, exist_ok=True)

    def process_item(self, item: PaperItem, spider):
        arxiv_id = item.get("arxiv_id", "")
        if not arxiv_id:
            return item

        pdf_path = os.path.join(self.pdf_dir, f"{arxiv_id}.pdf")

        if not os.path.exists(pdf_path):
            try:
                resp = self.session.get(f"https://arxiv.org/pdf/{arxiv_id}", timeout=60)
                if resp.status_code == 200 and len(resp.content) > 5000:
                    with open(pdf_path, "wb") as f:
                        f.write(resp.content)
                    spider.logger.info(f"[DOWNLOAD] {arxiv_id} PDF ({len(resp.content) // 1024}KB)")
                    item["downloaded"] = True
            except Exception as e:
                spider.logger.warning(f"[DOWNLOAD] {arxiv_id} PDF failed: {e}")
                item["downloaded"] = False
        else:
            item["downloaded"] = True

        # Convert to MD
        md_path = os.path.join(self.md_dir, f"{arxiv_id}.md")
        if os.path.exists(pdf_path) and not os.path.exists(md_path):
            try:
                import pymupdf4llm

                md_text = pymupdf4llm.to_markdown(pdf_path)
                title = item.get("title", arxiv_id)
                with open(md_path, "w") as f:
                    f.write(f"# {title} ({arxiv_id})\n\n> arXiv PDF\n\n{md_text}")
                spider.logger.info(f"[CONVERT] {arxiv_id} MD ({len(md_text)} chars)")
            except Exception as e:
                spider.logger.warning(f"[CONVERT] {arxiv_id} MD failed: {e}")

        return item
