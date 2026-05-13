# ─── 异步 PDF 下载器 ─────────────────────────
# hfpapers/pdf_downloader_async.py
# 基于 aiohttp 的并发 PDF 下载 + 转换

import asyncio
import logging
import os
from pathlib import Path
from typing import Callable, Optional

from hfpapers.config import get as cfg_get

logger = logging.getLogger("hfpapers.pdf_downloader")


class AsyncPdfDownloader:
    """异步 PDF 下载器

    aiohttp 并行下载 arXiv PDF，支持并发控制、重试、进度回调。

    用法:
        downloader = AsyncPdfDownloader(max_concurrent=8)
        results = await downloader.download_batch([
            {"arxiv_id": "2001.08361", "title": "FNO"},
            ...
        ])
    """

    def __init__(self, max_concurrent: int = 8, pdf_dir: str = None,
                 md_dir: str = None, progress_cb: Callable = None):
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
        """批量下载 PDF

        Args:
            papers: [{"arxiv_id", "title", "abstract", ...}, ...]

        Returns:
            [{"arxiv_id", "success", "pdf_path", "md_path", "error"}, ...]
        """
        logger.info(f"📥 批量下载: {len(papers)} 篇, {self.max_concurrent} 并发")

        try:
            import aiohttp
            import aiofiles
        except ImportError:
            logger.warning("aiohttp/aiofiles 不可用，回退到同步下载")
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
            f"✅ 下载完成: {success}/{len(papers)} 成功, "
            f"{self._stats['skipped']} 跳过, {self._stats['failed']} 失败"
        )
        return results

    async def _download_one(self, session, paper: dict) -> dict:
        """下载一篇 PDF + 转换 MD"""
        aid = paper["arxiv_id"]
        title = paper.get("title", aid)
        pdf_path = self.pdf_dir / f"{aid}.pdf"
        md_path = self.md_dir / f"{aid}.md"

        if pdf_path.exists():
            self._stats["skipped"] += 1
            result = {"arxiv_id": aid, "success": True, "pdf_path": str(pdf_path),
                      "md_path": str(md_path) if md_path.exists() else "", "error": ""}
            if self.progress_cb:
                self.progress_cb(result)
            return result

        async with self.sem:
            for attempt in range(3):
                try:
                    async with session.get(f"https://arxiv.org/pdf/{aid}") as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.read()
                        if len(data) < 5000:
                            continue  # 太小的文件不是有效PDF

                        # 写 PDF
                        import aiofiles
                        async with aiofiles.open(pdf_path, "wb") as f:
                            await f.write(data)

                        self._stats["downloaded"] += 1
                        logger.info(f"  PDF: {aid} ({len(data)//1024}KB)")

                        # 转 MD
                        md_path = await self._convert_to_md(pdf_path, md_path, title, aid)

                        result = {"arxiv_id": aid, "success": True,
                                  "pdf_path": str(pdf_path),
                                  "md_path": str(md_path) if md_path else "",
                                  "error": ""}
                        if self.progress_cb:
                            self.progress_cb(result)
                        return result

                except (asyncio.TimeoutError, Exception) as e:
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        self._stats["failed"] += 1
                        logger.warning(f"  ❌ {aid}: {e}")
                        result = {"arxiv_id": aid, "success": False,
                                  "pdf_path": "", "md_path": "", "error": str(e)}
                        if self.progress_cb:
                            self.progress_cb(result)
                        return result

        self._stats["failed"] += 1
        result = {"arxiv_id": aid, "success": False,
                  "pdf_path": "", "md_path": "", "error": "failed after 3 retries"}
        if self.progress_cb:
            self.progress_cb(result)
        return result

    async def _convert_to_md(self, pdf_path: Path, md_path: Path,
                              title: str, aid: str) -> Optional[Path]:
        """PDF → Markdown 转换（在线程池中执行 pymupdf4llm）"""
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
            logger.warning(f"  MD转换失败 {aid}: {e}")
            return None

    def _download_sync_fallback(self, papers: list[dict]) -> list[dict]:
        """回退到同步下载（当 aiohttp 不可用时）"""
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

                # 转换
                if pdf_path.exists() and not md_path.exists():
                    try:
                        import pymupdf4llm
                        md_text = pymupdf4llm.to_markdown(str(pdf_path))
                        with open(md_path, "w") as f:
                            f.write(f"# {title} ({aid})\n\n> arXiv PDF\n\n{md_text}")
                        self._stats["converted"] += 1
                    except Exception:
                        pass

                results.append({"arxiv_id": aid, "success": True,
                                "pdf_path": str(pdf_path) if pdf_path.exists() else "",
                                "md_path": str(md_path) if md_path.exists() else "",
                                "error": ""})
            except Exception as e:
                self._stats["failed"] += 1
                results.append({"arxiv_id": aid, "success": False,
                                "pdf_path": "", "md_path": "", "error": str(e)})

        session.close()
        return results
