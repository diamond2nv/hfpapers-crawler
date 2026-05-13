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
from datetime import datetime
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

    def __init__(
        self, db_path: str = "", data_dir: str = "", progress_cb: Optional[Callable] = None
    ):
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
                    # Normalize arxiv_id: strip version (v1, v2...), convert old
                    # format (category/YYMMNNN → YYMMNNN) to match OAI convention
                    arxiv_id = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id
                    arxiv_id = arxiv_id.split("/")[-1] if "/" in arxiv_id else arxiv_id
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

                    batch.append(
                        (
                            arxiv_id,
                            title,
                            authors,
                            abstract,
                            categories,
                            doi,
                            journal_ref,
                            update_date,
                        )
                    )
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
            logger.info(
                f"Kaggle download complete: {line_count:,} lines, imported {imported:,} papers, MD5: {md5[:12]}..."
            )
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

        # Download to persistent temporary directory
        tmp_dir = Path(tempfile.mkdtemp(prefix="kaggle_"))

        cmd = [
            "kaggle",
            "datasets",
            "download",
            KAGGLE_DATASET,
            "--path",
            str(tmp_dir),
        ]
        if force:
            cmd.append("--force")

        logger.info(f"Running: {' '.join(cmd)}")
        logger.info(f"Downloading to: {tmp_dir}")
        self.state.set_status("running", extra={"tmp_dir": str(tmp_dir), "progress": "starting"})

        # Use Popen so we can read output in real-time
        # NOTE: Kaggle CLI outputs tqdm progress bar on STDERR (not stdout).
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        # ─── Raw log file (rotation, 10MB×5) — full stdout+stderr留痕 ───
        raw_log = logging.handlers.RotatingFileHandler(
            tmp_dir / "kaggle_cli.log", maxBytes=10 * 1024 * 1024, backupCount=5
        )
        raw_log.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        raw_log.setLevel(logging.INFO)
        raw_logger = logging.getLogger(f"kaggle_raw_{tmp_dir.name}")
        raw_logger.setLevel(logging.INFO)
        raw_logger.addHandler(raw_log)
        raw_logger.propagate = False  # don't double-print to root logger
        raw_logger.info(
            "=== kaggle CLI download started ===\n"
            f"  Command: {' '.join(cmd)}\n"
            f"  CWD:     {tmp_dir}\n"
            f"  Time:    {datetime.now().isoformat()}"
        )

        # Monitor thread: read kaggle output + poll file size. Progress is
        # written to a lightweight .progress file (not SQLite) since it's
        # transient real-time data with no audit value.
        import re
        import threading
        import time

        # ─── Human-readable size parser ───────────────────────────────────
        size_units = {
            "k": 1024,
            "kb": 1024,
            "kib": 1024,
            "m": 1024**2,
            "mb": 1024**2,
            "mib": 1024**2,
            "g": 1024**3,
            "gb": 1024**3,
            "gib": 1024**3,
            "t": 1024**4,
            "tb": 1024**4,
            "tib": 1024**4,
        }

        def _parse_size(s: str) -> int | None:
            """Parse a size string like '1.00M', '722MB', '1.62G', '4.5GB' into bytes.

            Supports: K/KB/KiB, M/MB/MiB, G/GB/GiB, T/TB/TiB (case-insensitive)
            Returns None if unparseable.
            """
            s = s.strip()
            m = re.match(r"([\d.]+)\s*([a-zA-Z]+)", s)
            if not m:
                return None
            val = float(m.group(1))
            unit = m.group(2).lower()
            multiplier = size_units.get(unit)
            if multiplier is None:
                return None
            return int(val * multiplier)

        def _parse_tqdm_progress(line: str) -> tuple[str, str | None, int | None, int | None]:
            """Parse tqdm progress bar line like '1.00M/1.62G' or '0.7GB/4.5GB'

            Returns (progress_display_str, percentage_str, downloaded_bytes, total_bytes)
            where percentage_str is like '35%' or None if total unknown.
            Returns (line, None, None, None) if no progress bar found.
            """
            # Match: <cur>/<total> where each is e.g. 1.00M, 722MB, 0.7G, 1024KB
            m = re.search(
                r"([\d.]+)\s*([a-zA-Z]+)\s*/\s*([\d.]+)\s*([a-zA-Z]+)",
                line,
                re.IGNORECASE,
            )
            if not m:
                return line, None, None, None
            cur_bytes = _parse_size(f"{m.group(1)}{m.group(2)}")
            total_bytes = _parse_size(f"{m.group(3)}{m.group(4)}")
            if cur_bytes is None or total_bytes is None or total_bytes == 0:
                return line, None, cur_bytes, total_bytes
            pct = min(99, int(cur_bytes / total_bytes * 100))
            return line, f"{pct}%", cur_bytes, total_bytes

        # Progress file: lightweight transient state, NOT SQLite
        progress_file = tmp_dir / ".progress.json"

        def _write_progress(pct_str: str, downloaded_mb: int, total_mb: int):
            """Write transient progress to .progress.json file"""
            import json as json_mod

            now = datetime.now().isoformat()
            data = {
                "progress": pct_str,
                "downloaded_mb": downloaded_mb,
                "total_mb": total_mb,
                "tmp_dir": str(tmp_dir),
                "last_update": now,
            }
            try:
                progress_file.write_text(json_mod.dumps(data))
            except OSError:
                pass

        def _read_progress() -> dict:
            """Read transient progress from .progress.json file"""
            import json as json_mod

            try:
                if progress_file.exists():
                    return json_mod.loads(progress_file.read_text())
            except (OSError, json_mod.JSONDecodeError):
                pass
            return {}

        def _monitor():
            last_progress = ""
            while proc.poll() is None:
                # Read from stderr (where tqdm progress goes)
                # tqdm uses \r to overwrite the same line; read one char at a time
                line = ""
                try:
                    char = proc.stderr.read(1)
                    while char and char != "\r" and char != "\n":
                        line += char
                        char = proc.stderr.read(1)
                except (ValueError, OSError):
                    pass
                line = line.strip("\r\n\t ")

                if line:
                    raw_logger.info(f"[stderr] {line}")
                    logger.info(f"[kaggle] {line}")
                    _, pct_str, cur_bytes, total_bytes = _parse_tqdm_progress(line)
                    if pct_str:
                        dm = cur_bytes // (1024 * 1024) if cur_bytes else 0
                        tm = total_bytes // (1024 * 1024) if total_bytes else 0
                        _write_progress(pct_str, dm, tm)
                        last_progress = pct_str
                        continue

                # Also try stdout for any text messages
                try:
                    out_line = proc.stdout.readline()
                except (ValueError, OSError):
                    out_line = ""
                if out_line:
                    out_line = out_line.strip("\r\n\t ")
                    if out_line:
                        raw_logger.info(f"[stdout] {out_line}")
                        logger.info(f"[kaggle:out] {out_line}")

                # Fallback: poll zip file size for progress
                zip_files = list(tmp_dir.glob("*.zip"))
                if zip_files:
                    size_mb = int(zip_files[0].stat().st_size / (1024 * 1024))
                    progress = f"{size_mb} MB"
                    if progress != last_progress:
                        _write_progress(progress, size_mb, 0)
                        last_progress = progress
                else:
                    all_files = list(tmp_dir.iterdir())
                    if all_files:
                        size_mb = int(max(f.stat().st_size for f in all_files) / (1024 * 1024))
                        if size_mb > 0:
                            progress = f"{size_mb} MB"
                            if progress != last_progress:
                                _write_progress(progress, size_mb, 0)
                                last_progress = progress
                time.sleep(5)

        monitor_thread = threading.Thread(target=_monitor, daemon=True)
        monitor_thread.start()

        # Expose progress reader so CLI can use it
        self._progress_reader = _read_progress

        # Wait for download to complete
        # Long timeout: domestic network may be slow/unstable; 4h is acceptable
        # for overnight downloads. The monitor thread handles progress display.
        proc.wait(timeout=14400)
        if proc.returncode != 0:
            remaining = proc.stdout.read() if proc.stdout else ""
            error_msg = remaining.strip() or "kaggle CLI returned non-zero exit code"
            raise RuntimeError(f"kaggle download failed: {error_msg}")

        # Download done — mark in SQLite only once
        self.state.set_status(
            "running",
            extra={
                "tmp_dir": str(tmp_dir),
                "progress": "extracting",
            },
        )

        # Find downloaded archive file
        zip_files = list(tmp_dir.glob("*.zip")) + list(tmp_dir.glob("*.gz"))
        if not zip_files:
            # May be a directly downloaded file
            jsonl_files = list(tmp_dir.glob("*.jsonl")) + list(tmp_dir.glob("*.json"))
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
        - .json (JSONL-format) file — Kaggle source uses this misleading extension
        - .jsonl.gz / .json.gz file (needs extraction)
        - In nested directory
        """
        gz_files = list(download_dir.rglob("*.jsonl.gz")) + list(download_dir.rglob("*.json.gz"))
        jsonl_files = list(download_dir.rglob("*.jsonl"))
        json_files = list(download_dir.rglob("*.json"))

        if jsonl_files:
            src = jsonl_files[0]
            import shutil

            shutil.copy2(str(src), str(output))
            logger.info(f"Copying JSONL: {src.name} → {output}")
        elif json_files:
            # Kaggle source uses .json extension but content is JSONL
            src = json_files[0]
            import shutil

            shutil.copy2(str(src), str(output))
            logger.info(f"Copying JSON (JSONL-format): {src.name} → {output}")
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
