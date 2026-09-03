#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ─── Async PDF Downloader ─────────────────────────
# hfpapers/pdf_downloader_async.py
# aiohttp-based concurrent PDF download + conversion

import asyncio
import logging
import os
from pathlib import Path
from typing import Callable, Optional

from hfpapers.config import get as cfg_get

logger = logging.getLogger("hfpapers.pdf_downloader")


class AsyncPdfDownloader:
    """Async PDF Downloader

    aiohttp parallel download of arXiv PDFs, supports concurrency control, retry, progress callback.

    Usage:
        downloader = AsyncPdfDownloader(max_concurrent=8)
        results = await downloader.download_batch([
            {"arxiv_id": "2001.08361", "title": "FNO"},
            ...
        ])
    """

    def __init__(
        self,
        max_concurrent: int = 8,
        pdf_dir: str = None,
        md_dir: str = None,
        progress_cb: Callable = None,
    ):
        self.max_concurrent = max_concurrent
        self.sem = asyncio.Semaphore(max_concurrent)
        self.pdf_dir = Path(pdf_dir or cfg_get("paths.pdf_dir", "pdfs"))
        self.md_dir = Path(md_dir or cfg_get("paths.md_dir", "mds"))
        self.progress_cb = progress_cb
        os.makedirs(self.pdf_dir, exist_ok=True)
        os.makedirs(self.md_dir, exist_ok=True)
        self._stats = {"downloaded": 0, "converted": 0, "skipped": 0, "failed": 0}

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    async def download_batch(self, papers: list[dict]) -> list[dict]:
        """Batch download PDFs

        Args:
            papers: [{"arxiv_id", "title", "abstract", ...}, ...]

        Returns:
            [{"arxiv_id", "success", "pdf_path", "md_path", "error"}, ...]
        """
        logger.info(f"📥 Batch download: {len(papers)} papers, {self.max_concurrent} concurrent")

        try:
            import aiohttp
        except ImportError:
            logger.warning("aiohttp/aiofiles unavailable, falling back to sync download")
            return self._download_sync_fallback(papers)

        async with aiohttp.ClientSession(
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=aiohttp.ClientTimeout(total=120),
        ) as session:
            tasks = []
            for paper in papers:
                tasks.append(self._download_one(session, paper))
            results = await asyncio.gather(*tasks)

        success = sum(1 for r in results if r["success"])
        logger.info(
            f"✅ Download complete: {success}/{len(papers)} successful, "
            f"{self._stats['skipped']} skipped, {self._stats['failed']} failed"
        )
        return results

    async def _download_one(self, session, paper: dict) -> dict:
        """Download one PDF + convert to MD"""
        aid = paper["arxiv_id"]
        title = paper.get("title", aid)
        pdf_path = self.pdf_dir / f"{aid}.pdf"
        md_path = self.md_dir / f"{aid}.md"

        if pdf_path.exists():
            self._stats["skipped"] += 1
            result = {
                "arxiv_id": aid,
                "success": True,
                "pdf_path": str(pdf_path),
                "md_path": str(md_path) if md_path.exists() else "",
                "error": "",
            }
            if self.progress_cb:
                self.progress_cb(result)
            return result

        async with self.sem:
            for attempt in range(3):
                try:
                    try:
                        async with session.get(f"https://arxiv.org/pdf/{aid}") as resp:
                            if resp.status != 200:
                                self._last_error = f"HTTP {resp.status}"
                                raise ConnectionError(self._last_error)
                            data = await resp.read()
                            transport = "tcp"
                    except Exception as e:
                        # CN-network fallback: TCP to arXiv is reset at the
                        # TLS-SNI layer; QUIC (UDP 443) is not. Try HTTP/3 once.
                        self._last_error = f"tcp-fail ({e}); trying quic"
                        from hfpapers.arxiv_transport import async_quic_fetch

                        q = await async_quic_fetch(
                            f"https://arxiv.org/pdf/{aid}", "pdf", timeout=90.0
                        )
                        if not q.ok:
                            self._last_error = q.error or "quic-fail"
                            raise ConnectionError(self._last_error)
                        data = q.data
                        transport = "quic"
                        self._quic_used = getattr(self, "_quic_used", 0) + 1

                    if len(data) < 5000:
                        self._last_error = "PDF too small (<5KB)"
                        raise ConnectionError(self._last_error)

                    # Write PDF (sync open — aiofiles is optional; PDFs are
                    # small enough that a short blocking write is acceptable)
                    pdf_path.write_bytes(data)

                    self._stats["downloaded"] += 1
                    logger.info(
                        f"  PDF: {aid} ({len(data) // 1024}KB via {transport})"
                    )

                    # Acquisition audit row (transport chain evidence)
                    try:
                        from hfpapers.arxiv_transport import (
                            FetchResult,
                            log_acquisition,
                        )

                        log_acquisition(
                            FetchResult(
                                ok=True, kind="pdf",
                                url=f"https://arxiv.org/pdf/{aid}",
                                transport=transport, data=data,
                                tls_verified=True,
                            ).audit_row(aid)
                        )
                    except Exception:
                        pass  # audit must never block the download

                    # Convert to MD
                    md_path = await self._convert_to_md(pdf_path, md_path, title, aid)

                    result = {
                        "arxiv_id": aid,
                        "success": True,
                        "pdf_path": str(pdf_path),
                        "md_path": str(md_path) if md_path else "",
                        "error": "",
                    }
                    if self.progress_cb:
                        self.progress_cb(result)
                    return result

                except (asyncio.TimeoutError, Exception) as e:
                    self._last_error = str(e)
                    if attempt < 2:
                        await asyncio.sleep(2**attempt)
                    else:
                        self._stats["failed"] += 1
                        logger.warning(f"  ❌ {aid}: {e}")
                        result = {
                            "arxiv_id": aid,
                            "success": False,
                            "pdf_path": "",
                            "md_path": "",
                            "error": str(e),
                        }
                        if self.progress_cb:
                            self.progress_cb(result)
                        return result

        self._stats["failed"] += 1
        err = getattr(self, "_last_error", "failed after 3 retries")
        result = {
            "arxiv_id": aid,
            "success": False,
            "pdf_path": "",
            "md_path": "",
            "error": err,
        }
        if self.progress_cb:
            self.progress_cb(result)
        return result

    async def _convert_to_md(
        self, pdf_path: Path, md_path: Path, title: str, aid: str
    ) -> Optional[Path]:
        """PDF → Markdown conversion (runs pymupdf4llm in thread pool)"""
        try:
            import pymupdf4llm
        except ImportError:
            return None

        if md_path.exists():
            return md_path

        loop = asyncio.get_event_loop()
        try:
            md_text = await loop.run_in_executor(None, pymupdf4llm.to_markdown, str(pdf_path))
            with open(md_path, "w") as f:
                f.write(f"# {title} ({aid})\n\n> arXiv PDF\n\n{md_text}")
            self._stats["converted"] += 1
            logger.info(f"  MD: {aid} ({len(md_text)} chars)")
            return md_path
        except Exception as e:
            logger.warning(f"  MD conversion failed {aid}: {e}")
            return None

    def _download_sync_fallback(self, papers: list[dict]) -> list[dict]:
        """Fallback to synchronous download (when aiohttp is unavailable)"""
        import requests

        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        results = []

        for paper in papers:
            aid = paper["arxiv_id"]
            title = paper.get("title", aid)
            pdf_path = self.pdf_dir / f"{aid}.pdf"
            md_path = self.md_dir / f"{aid}.md"

            try:
                if not pdf_path.exists():
                    resp = session.get(f"https://arxiv.org/pdf/{aid}", timeout=60)
                    if resp.status_code == 200 and len(resp.content) > 5000:
                        pdf_path.write_bytes(resp.content)
                        self._stats["downloaded"] += 1

                # Convert
                if pdf_path.exists() and not md_path.exists():
                    try:
                        import pymupdf4llm

                        md_text = pymupdf4llm.to_markdown(str(pdf_path))
                        with open(md_path, "w") as f:
                            f.write(f"# {title} ({aid})\n\n> arXiv PDF\n\n{md_text}")
                        self._stats["converted"] += 1
                    except Exception:
                        pass

                results.append(
                    {
                        "arxiv_id": aid,
                        "success": True,
                        "pdf_path": str(pdf_path) if pdf_path.exists() else "",
                        "md_path": str(md_path) if md_path.exists() else "",
                        "error": "",
                    }
                )
            except Exception as e:
                self._stats["failed"] += 1
                results.append(
                    {
                        "arxiv_id": aid,
                        "success": False,
                        "pdf_path": "",
                        "md_path": "",
                        "error": str(e),
                    }
                )

        session.close()
        return results
