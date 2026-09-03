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
        """Batch download PDFs.

        TCP phase runs first (1 attempt per paper — on CN networks a TCP
        reset is deterministic, retries only waste the batch window); every
        TCP failure is then re-fetched in ONE quic_batch_fetch call (single
        connection, N concurrent HTTP/3 streams — amortised congestion-window
        ramp instead of N handshakes).
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
            tasks = [
                self._download_one(session, paper, attempts=1) for paper in papers
            ]
            results = await asyncio.gather(*tasks)

        # QUIC re-fetch of every TCP failure (one connection, many streams)
        failed = [r for r in results if not r["success"]]
        if failed:
            results = await self._quic_refetch(failed, papers)

        success = sum(1 for r in results if r["success"])
        logger.info(
            f"✅ Download complete: {success}/{len(papers)} successful, "
            f"{self._stats['skipped']} skipped, {self._stats['failed']} failed"
        )
        return results

    async def _quic_refetch(
        self, failed: list[dict], papers: list[dict]
    ) -> list[dict]:
        """Batch QUIC fallback for papers that lost the TCP phase."""
        try:
            from hfpapers.arxiv_transport import quic_batch_fetch
        except ImportError:
            return failed  # quic extra missing — leave results as-is

        # Filter failed results that still have no pdf on disk
        retry_papers = []
        for r in failed:
            if not r["pdf_path"]:
                aid = r["arxiv_id"]
                src = next((p for p in papers if p["arxiv_id"] == aid), {})
                if src:
                    retry_papers.append((aid, "pdf"))
        if not retry_papers:
            return failed

        logger.info(f"🔁 QUIC re-fetch batch: {len(retry_papers)} papers")
        # sinks: stream straight to each final pdf path — peak RAM stays
        # O(streams × 512KB) instead of O(total re-fetched payload).
        sinks = {aid: self.pdf_dir / f"{aid}.pdf" for aid, _k in retry_papers}
        try:
            fetched = quic_batch_fetch(retry_papers, timeout=180.0, sinks=sinks)
        except Exception as e:
            logger.warning(f"  QUIC batch failed: {e}")
            return failed

        restored = {}
        for (aid, _kind), fr in zip(retry_papers, fetched):
            restored[aid] = fr

        final = []
        for r in failed:
            aid = r["arxiv_id"]
            fr = restored.get(aid)
            if fr is not None and fr.ok:
                src = next((p for p in papers if p["arxiv_id"] == aid), {})
                title = src.get("title", aid)
                pdf_path = self.pdf_dir / f"{aid}.pdf"
                md_path = self.md_dir / f"{aid}.md"
                # Sunk stream: file is already complete on disk (data=b"").
                # _persist_pdf skips the write and does stats/audit/convert.
                pers = await self._persist_pdf(
                    aid, title, pdf_path, md_path, fr.data or None, "quic"
                )
                final.append(pers)
            else:
                # Failed sunk stream leaves an INCOMPLETE file on disk (its
                # head was flushed during transfer) — remove it unconditionally
                # so the skip-check (pdf_path.exists()) can't mistake a partial
                # download for a completed one.
                partial = self.pdf_dir / f"{aid}.pdf"
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    pass
                self._stats["failed"] += 1
                r["error"] = (fr.error if fr is not None else "quic refetch skipped") or r["error"]
                final.append(r)
        return final

    async def _download_one(
        self, session, paper: dict, attempts: int = 3, quic_fallback: bool = True
    ) -> dict:
        """Download one PDF + convert to MD.

        attempts: retry budget for the transport phase (batch passes 1 —
        CN TCP resets are deterministic and retries waste the batch window).
        quic_fallback: per-paper HTTP/3 retry on TCP failure (batch disables
        it and re-fetches ALL failures in one quic_batch_fetch connection).
        """
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
            for attempt in range(attempts):
                try:
                    try:
                        async with session.get(f"https://arxiv.org/pdf/{aid}") as resp:
                            if resp.status != 200:
                                self._last_error = f"HTTP {resp.status}"
                                raise ConnectionError(self._last_error)
                            data = await resp.read()
                            transport = "tcp"
                    except Exception as e:
                        if not quic_fallback:
                            # batch mode: no per-paper QUIC — the unified
                            # _quic_refetch handles all TCP failures together
                            raise ConnectionError(f"tcp-fail ({e})") from e
                        # Single-paper CN fallback: TCP to arXiv is reset at
                        # the TLS-SNI layer; QUIC (UDP 443) is not.
                        self._last_error = f"tcp-fail ({e}); trying quic"
                        from hfpapers.arxiv_transport import async_quic_fetch

                        q = await async_quic_fetch(
                            f"https://arxiv.org/pdf/{aid}", "pdf", timeout=90.0
                        )
                        if not q.ok:
                            self._last_error = q.error or "quic-fail"
                            raise ConnectionError(self._last_error) from None
                        data = q.data
                        transport = "quic"
                        self._quic_used = getattr(self, "_quic_used", 0) + 1

                    if len(data) < 5000:
                        self._last_error = "PDF too small (<5KB)"
                        raise ConnectionError(self._last_error)

                    return await self._persist_pdf(
                        aid, title, pdf_path, md_path, data, transport
                    )

                except (asyncio.TimeoutError, Exception) as e:
                    self._last_error = str(e)
                    if attempt < attempts - 1:
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
        err = getattr(self, "_last_error", f"failed after {attempts} retries")
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

    async def _persist_pdf(
        self,
        aid: str,
        title: str,
        pdf_path,
        md_path,
        data: Optional[bytes],
        transport: str,
    ) -> dict:
        """Write PDF + stats + acquisition audit + MD conversion (shared by
        the single-paper path and the batch QUIC refetch path).

        data=None means the file is already complete on disk (sunk QUIC
        stream) — the write is skipped, stats/audit/convert still run.
        """
        if data is not None:
            # Write PDF (sync open — aiofiles is optional; PDFs are small
            # enough that a short blocking write is acceptable)
            pdf_path.write_bytes(data)

        self._stats["downloaded"] += 1
        n_bytes = len(data) if data is not None else (
            pdf_path.stat().st_size if pdf_path.exists() else 0
        )
        logger.info(f"  PDF: {aid} ({n_bytes // 1024}KB via {transport})")

        # Acquisition audit row (transport chain evidence)
        try:
            from hfpapers.arxiv_transport import FetchResult, file_sha256, log_acquisition

            log_acquisition(
                FetchResult(
                    ok=True, kind="pdf",
                    url=f"https://arxiv.org/pdf/{aid}",
                    transport=transport, data=data or b"",
                    tls_verified=True,
                    # Sunk stream: content is on disk — hash the file, not the
                    # (empty) residual, so the audit row stays meaningful.
                    sha256=(
                        file_sha256(pdf_path)
                        if data is None and pdf_path.exists()
                        else ""
                    ),
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
