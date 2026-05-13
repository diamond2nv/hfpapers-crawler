"""KaggleDownloader — arXiv 元数据集从 Kaggle 下载

使用 kaggle CLI 下载 Cornell-University/arxiv 数据集（JSON Lines，约 4.5G 压缩）。
复用 BaseDownloader 框架提供进度跟踪、checksum 校验、断点续传。

依赖：kaggle CLI（pip install kaggle）+ Kaggle API Token (~/.kaggle/kaggle.json)
"""

import gzip
import json as json_mod
import logging
import os
import sqlite3
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Callable

from hfpclawer.download.base import BaseDownloader

logger = logging.getLogger("hfpclawer.download.kaggle")

# Kaggle 数据集信息
KAGGLE_DATASET = "Cornell-University/arxiv"
JSONL_FILENAME = "arxiv_metadata.jsonl"


class KaggleDownloader(BaseDownloader):
    """从 Kaggle 下载 arXiv 全量元数据集

    用 kaggle CLI 下载 → 解压 .zip/.gz → 存储为 JSONL。
    支持 checksum（MD5）校验和断点续传。
    """

    source_name: str = "kaggle"

    def __init__(self, db_path: str = "",
                 data_dir: str = "",
                 progress_cb: Optional[Callable] = None):
        self.data_dir = data_dir or self._default_data_dir()
        super().__init__(db_path=db_path, progress_cb=progress_cb)

    def _default_db_path(self) -> str:
        """默认状态数据库路径"""
        from hfpapers.config import get as cfg_get
        base = Path(__file__).resolve().parent.parent.parent
        return str(base / cfg_get("db.path", "data/arxiv_meta.db"))

    def _default_data_dir(self) -> str:
        """默认数据目录"""
        from hfpapers.config import get as cfg_get
        base = Path(__file__).resolve().parent.parent.parent
        return str(base / cfg_get("data.dir", "data"))

    def jsonl_path(self) -> Path:
        """JSONL 输出文件路径"""
        return Path(self.data_dir) / JSONL_FILENAME

    def _init_arxiv_meta_db(self):
        """确保 arxiv_meta 表存在（复用 OAI 的 schema）"""
        from hfpclawer.download.oai import ArxivMetaDB, MIGRATE_ADD_SOURCE
        meta_db = ArxivMetaDB(self.db_path)
        return meta_db

    def _import_jsonl_to_sqlite(self, jsonl_path: Path) -> int:
        """将 JSONL 文件导入 arxiv_meta 表，返回导入行数

        JSONL 格式: {"id": "0704.0001", "title": "...", ...}
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
                    # 标准 arxiv_id 格式（去掉版本号）
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

        logger.info(f"Kaggle JSONL 导入完成: {total:,} 篇")
        return total

    def run(self, force: bool = False, **kwargs) -> int:
        """执行 Kaggle 数据集下载

        Args:
            force: 即使 JSONL 已存在也强制重新下载

        Returns:
            下载的 JSONL 文件行数（论文数），0 表示已存在且未强制
        """
        jsonl = self.jsonl_path()

        # 检查是否已下载
        if jsonl.exists() and not force:
            md5 = self.state.checksum_file(str(jsonl))
            saved = self.state.get().get("checksum", "")
            if saved and saved == md5:
                logger.info(f"数据集已是最新: {jsonl} (MD5: {md5[:12]}...)")
                return 0
            logger.info(f"数据集存在但 checksum 不一致: {saved} != {md5}")

        # 状态：下载中
        self.state.set_status("running", error="")
        logger.info(f"从 Kaggle 下载数据集: {KAGGLE_DATASET}")
        logger.info("首次下载约 30 分钟，压缩包 ~4.5G")

        # 确保数据目录存在
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)

        try:
            # 使用 kaggle CLI 下载
            download_dir = self._download_kaggle(force)
            # 解压为 JSONL
            jsonl_path = self._extract_to_jsonl(download_dir, jsonl)
            # 计算 checksum
            md5 = self.state.checksum_file(str(jsonl_path))
            # 统计行数
            line_count = self._count_lines(str(jsonl_path))
            # 导入到 SQLite
            imported = self._import_jsonl_to_sqlite(jsonl_path)
            # 更新状态
            self.state.mark_done()
            self._update_progress(fetched=imported, new_count=imported, checksum=md5)
            logger.info(f"Kaggle 下载完成: {line_count:,} 行, 导入 {imported:,} 篇, MD5: {md5[:12]}...")
            return imported

        except Exception as e:
            self.state.mark_failed(str(e))
            logger.error(f"Kaggle 下载失败: {e}")
            raise

    def _download_kaggle(self, force: bool) -> Path:
        """使用 kaggle CLI 下载数据集，返回下载目录

        Returns:
            Path: 包含下载文件的临时目录
        """
        # 检查 kaggle CLI 是否可用
        try:
            subprocess.run(["kaggle", "--version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("kaggle CLI 未安装: pip install kaggle")

        # 检查 API Token
        kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
        if not kaggle_json.exists():
            raise RuntimeError(
                "Kaggle API Token 未配置。请创建 ~/.kaggle/kaggle.json:\n"
                '  {"username":"xxx","key":"xxx"}'
            )

        # 下载到临时目录
        with tempfile.TemporaryDirectory(prefix="kaggle_") as tmp:
            tmp_dir = Path(tmp)

            cmd = [
                "kaggle", "datasets", "download",
                KAGGLE_DATASET,
                "--path", str(tmp_dir),
            ]
            if force:
                cmd.append("--force")

            logger.info(f"运行: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=3600,
            )
            if result.returncode != 0:
                raise RuntimeError(f"kaggle 下载失败: {result.stderr.strip()}")

            # 查找下载的压缩文件
            zip_files = list(tmp_dir.glob("*.zip")) + list(tmp_dir.glob("*.gz"))
            if not zip_files:
                # 可能是直接下载了文件
                jsonl_files = list(tmp_dir.glob("*.jsonl"))
                if jsonl_files:
                    return tmp_dir
                raise FileNotFoundError(f"未找到下载文件在 {tmp_dir}")

            download_dir = Path(tempfile.mkdtemp(prefix="kaggle_extract_"))
            try:
                for zf in zip_files:
                    if str(zf).endswith(".zip"):
                        with zipfile.ZipFile(zf, "r") as z:
                            z.extractall(download_dir)
                        logger.info(f"解压 ZIP: {zf.name} → {download_dir}")
                    else:
                        # .gz 文件
                        out_name = zf.stem  # 去掉 .gz
                        out_path = download_dir / out_name
                        with gzip.open(zf, "rb") as fin:
                            with open(out_path, "wb") as fout:
                                fout.write(fin.read())
                        logger.info(f"解压 GZ: {zf.name} → {out_path}")
                return download_dir
            except Exception:
                import shutil
                shutil.rmtree(download_dir, ignore_errors=True)
                raise

    def _extract_to_jsonl(self, download_dir: Path, output: Path) -> Path:
        """从下载目录中找到 JSONL 文件，复制到输出路径

        处理以下情况：
        - 直接是 .jsonl 文件
        - 是 .jsonl.gz 文件（需解压）
        - 在嵌套目录中
        """
        jsonl_files = list(download_dir.rglob("*.jsonl"))
        gz_files = list(download_dir.rglob("*.jsonl.gz"))

        if jsonl_files:
            src = jsonl_files[0]
            import shutil
            shutil.copy2(str(src), str(output))
            logger.info(f"复制 JSONL: {src.name} → {output}")
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
            logger.info(f"解压 GZ → JSONL: {src.name} → {output}")
        else:
            # 列出目录内容帮助诊断
            all_files = list(download_dir.rglob("*"))
            files_str = "\n  ".join(str(f.relative_to(download_dir)) for f in all_files[:20])
            raise FileNotFoundError(
                f"未在 {download_dir} 中找到 JSONL 文件。内容:\n  {files_str}"
            )

        return output

    @staticmethod
    def _count_lines(filepath: str) -> int:
        """快速统计 JSONL 行数"""
        count = 0
        with open(filepath, "rb") as f:
            for _ in f:
                count += 1
        return count
