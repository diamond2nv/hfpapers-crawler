#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KaggleDownloader — arXiv metadata dataset download from Kaggle

Download Cornell-University/arxiv dataset via kaggle CLI (JSON Lines, ~4.5G compressed).
Reuses BaseDownloader framework for progress tracking, checksum validation, resume support.

Depends on: kaggle CLI (pip install kaggle) + Kaggle API Token (~/.kaggle/kaggle.json)
"""

import gzip
import json as json_mod
import logging
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Optional

from hfpclawer.download.base import BaseDownloader

logger = logging.getLogger("hfpclawer.download.kaggle")

# Kaggle dataset info
KAGGLE_DATASET = "Cornell-University/arxiv"
JSONL_FILENAME = "arxiv_metadata.jsonl"


class KaggleDownloader(BaseDownloader):
    """Download arXiv full metadata from Kaggle

    Download via kaggle CLI → unzip .zip/.gz → store as JSONL.
    Supports checksum (MD5) validation and resume.
    """

    source_name: str = "kaggle"

    def __init__(self, db_path: str = "",
                 data_dir: str = "",
                 progress_cb: Optional[Callable] = None):
        self.data_dir = data_dir or self._default_data_dir()
        super().__init__(db_path=db_path, progress_cb=progress_cb)

    def _default_db_path(self) -> str:
        """Default state database path"""
        from hfpapers.config import get as cfg_get
        base = Path(__file__).resolve().parent.parent.parent
        return str(base / cfg_get("db.path", "data/arxiv_meta.db"))

    def _default_data_dir(self) -> str:
        """Default data directory"""
        from hfpapers.config import get as cfg_get
        base = Path(__file__).resolve().parent.parent.parent
        return str(base / cfg_get("data.dir", "data"))

    def jsonl_path(self) -> Path:
        """JSONL output file path"""
        return Path(self.data_dir) / JSONL_FILENAME

    def _init_arxiv_meta_db(self):
        """Ensure arxiv_meta table exists (reusing OAI schema)"""
        from hfpclawer.download.oai import ArxivMetaDB
        meta_db = ArxivMetaDB(self.db_path)
        return meta_db

    def _import_jsonl_to_sqlite(self, jsonl_path: Path) -> int:
        """Import JSONL file into arxiv_meta table, return imported row count

        JSONL format: {"id": "0704.0001", "title": "...", ...}
        """
        meta_db = self._init_arxiv_meta_db()
        batch = []
        total = 0
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    paper = json_mod.loads(line)
                    arxiv_id = paper.get("id", "")
                    if not arxiv_id:
                        continue
                    # Standard arxiv_id format (strip version number)
                    arxiv_id = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id
                    title = paper.get("title", "") or ""
                    authors = paper.get("authors", "") or ""
                    if isinstance(authors, list):
                        authors = ", ".join(authors)
                    abstract = paper.get("abstract", "") or ""
                    categories = paper.get("categories", "") or ""
                    if isinstance(categories, list):
                        categories = " ".join(categories)
                    doi = paper.get("doi", "") or ""
                    journal_ref = paper.get("journal-ref", "") or ""
                    update_date = paper.get("update_date", "") or ""

                    batch.append((arxiv_id, title, authors, abstract,
                                  categories, doi, journal_ref, update_date))
                    total += 1

                    if len(batch) >= 500:
                        meta_db.insert_batch(batch, source="kaggle")
                        batch = []
                except json_mod.JSONDecodeError:
                    continue

        if batch:
            meta_db.insert_batch(batch, source="kaggle")

        logger.info(f"Kaggle JSONL import complete: {total:,} papers")
        return total

    def run(self, force: bool = False, **kwargs) -> int:
        """Execute Kaggle dataset download

        Args:
            force: Force re-download even if JSONL exists

        Returns:
            JSONL file line count (papers), 0 means exists and not forced
        """
        jsonl = self.jsonl_path()

        # Check if already downloaded
        if jsonl.exists() and not force:
            md5 = self.state.checksum_file(str(jsonl))
            saved = self.state.get().get("checksum", "")
            if saved and saved == md5:
                logger.info(f"Dataset is up to date: {jsonl} (MD5: {md5[:12]}...)")
                return 0
            logger.info(f"Dataset exists but checksum mismatch: {saved} != {md5}")

        # Status: downloading
        self.state.set_status("running", error="")
        logger.info(f"Downloading dataset from Kaggle: {KAGGLE_DATASET}")
        logger.info("First download takes ~30 min, compressed ~4.5G")

        # Ensure data directory exists
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)

        try:
            # Download using kaggle CLI
            download_dir = self._download_kaggle(force)
            # Extract to JSONL
            jsonl_path = self._extract_to_jsonl(download_dir, jsonl)
            # Calculate checksum
            md5 = self.state.checksum_file(str(jsonl_path))
            # Count lines
            line_count = self._count_lines(str(jsonl_path))
            # Import to SQLite
            imported = self._import_jsonl_to_sqlite(jsonl_path)
            # Update status
            self.state.mark_done()
            self._update_progress(fetched=imported, new_count=imported, checksum=md5)
            logger.info(f"Kaggle download complete: {line_count:,} lines, imported {imported:,} papers, MD5: {md5[:12]}...")
            return imported

        except Exception as e:
            self.state.mark_failed(str(e))
            logger.error(f"Kaggle download failed: {e}")
            raise

    def _download_kaggle(self, force: bool) -> Path:
        """Download dataset using kaggle CLI, return download directory

        Returns:
            Path: Temporary directory containing downloaded files
        """
        # Check if kaggle CLI is available
        try:
            subprocess.run(["kaggle", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("kaggle CLI not installed: pip install kaggle")

        # Check API Token
        kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
        if not kaggle_json.exists():
            raise RuntimeError(
                "Kaggle API Token not configured. Please create ~/.kaggle/kaggle.json:\n"
                '  {"username":"xxx","key":"xxx"}'
            )

        # Download to temporary directory
        with tempfile.TemporaryDirectory(prefix="kaggle_") as tmp:
            tmp_dir = Path(tmp)

            cmd = [
                "kaggle", "datasets", "download",
                KAGGLE_DATASET,
                "--path", str(tmp_dir),
            ]
            if force:
                cmd.append("--force")

            logger.info(f"Running: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=3600,
            )
            if result.returncode != 0:
                raise RuntimeError(f"kaggle download failed: {result.stderr.strip()}")

            # Find downloaded archive file
            zip_files = list(tmp_dir.glob("*.zip")) + list(tmp_dir.glob("*.gz"))
            if not zip_files:
                # May be a directly downloaded file
                jsonl_files = list(tmp_dir.glob("*.jsonl"))
                if jsonl_files:
                    return tmp_dir
                raise FileNotFoundError(f"No downloaded files found in {tmp_dir}")

            download_dir = Path(tempfile.mkdtemp(prefix="kaggle_extract_"))
            try:
                for zf in zip_files:
                    if str(zf).endswith(".zip"):
                        with zipfile.ZipFile(zf, "r") as z:
                            z.extractall(download_dir)
                        logger.info(f"Extracting ZIP: {zf.name} → {download_dir}")
                    else:
                        # .gz file
                        out_name = zf.stem  # Remove .gz
                        out_path = download_dir / out_name
                        with gzip.open(zf, "rb") as fin:
                            with open(out_path, "wb") as fout:
                                fout.write(fin.read())
                        logger.info(f"Extracting GZ: {zf.name} → {out_path}")
                return download_dir
            except Exception:
                import shutil
                shutil.rmtree(download_dir, ignore_errors=True)
                raise

    def _extract_to_jsonl(self, download_dir: Path, output: Path) -> Path:
        """Find JSONL file in download directory, copy to output path

        Handles the following cases:
        - Direct .jsonl file
        - .jsonl.gz file (needs extraction)
        - In nested directory
        """
        jsonl_files = list(download_dir.rglob("*.jsonl"))
        gz_files = list(download_dir.rglob("*.jsonl.gz"))

        if jsonl_files:
            src = jsonl_files[0]
            import shutil
            shutil.copy2(str(src), str(output))
            logger.info(f"Copying JSONL: {src.name} → {output}")
        elif gz_files:
            src = gz_files[0]
            chunk_size = 64 * 1024 * 1024  # 64MB chunks
            with gzip.open(src, "rb") as f_in:
                with open(output, "wb") as f_out:
                    while True:
                        chunk = f_in.read(chunk_size)
                        if not chunk:
                            break
                        f_out.write(chunk)
            logger.info(f"Extracting GZ → JSONL: {src.name} → {output}")
        else:
            # List directory contents for diagnostics
            all_files = list(download_dir.rglob("*"))
            files_str = "\n  ".join(str(f.relative_to(download_dir)) for f in all_files[:20])
            raise FileNotFoundError(
                f"No JSONL file found in {download_dir}. Contents:\n  {files_str}"
            )

        return output

    @staticmethod
    def _count_lines(filepath: str) -> int:
        """Quick count of JSONL lines"""
        count = 0
        with open(filepath, "rb") as f:
            for _ in f:
                count += 1
        return count
