# ─── OAI-PMH Batch Download arXiv Metadata ────────
# scripts/download_arxiv_oai.py
# Batch download arXiv metadata to SQLite FTS5 index using arXiv OAI-PMH interface
# Supports resume from breakpoint, incremental updates, priority queue, background running

"""
Usage:
    # Full download (priority high to low)
    python scripts/download_arxiv_oai.py --all

    # Incremental update only (new papers since last)
    python scripts/download_arxiv_oai.py --incremental

    # Background download (nohup)
    nohup python scripts/download_arxiv_oai.py --all --background > download.log 2>&1 &

    # Check progress
    python scripts/download_arxiv_oai.py --status

Configuration:
    - First run auto-creates/uses data/arxiv_meta.db (FTS5 index)
    - Download state saved in data/oai_download_state.json
    - Supports Ctrl+C interrupt with resume capability
"""

import json
import logging
import re
import sqlite3
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("arxiv_oai")

# ─── Paths ────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "arxiv_meta.db"
STATE_PATH = DATA_DIR / "oai_download_state.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ─── OAI-PMH Configuration ───────────────────────────
OAI_BASE = "https://export.arxiv.org/oai2"
MAX_RETRIES = 5
RETRY_BACKOFF = [2, 5, 10, 30, 60]  # seconds
PAGE_SIZE = 1000  # OAI-PMH max records per page
BATCH_WRITE = 500  # records per DB batch write
RATE_LIMIT = 2.0  # request interval (seconds) — arXiv recommends 4/s peak + 1s sleep

# ─── Download Priorities ─────────────────────────────
# Sorted by relevance to our domain, higher priority first
DOWNLOAD_PRIORITIES = [
    # Tier 1: AI/ML/PDE Core
    "cs:cs:AI",      # Artificial Intelligence
    "cs:cs:LG",      # Machine Learning
    "cs:cs:NA",      # Numerical Analysis
    "cs:cs:NE",      # Neural and Evolutionary Computing
    "cs:cs:CV",      # Computer Vision
    "cs:cs:CL",      # Computation and Language
    "math:math:AP",  # Analysis of PDEs
    "math:math:NA",  # Numerical Analysis (Math)
    "math:math:OC",  # Optimization and Control
    "stat:stat:ML",  # Machine Learning (Stats)
    "stat:stat:CO",  # Computation (Stats)

    # Tier 2: Related fields
    "cs:cs:CE",      # Computational Engineering, Finance, and Science
    "cs:cs:IR",      # Information Retrieval
    "cs:cs:IT",      # Information Theory
    "cs:cs:DS",      # Data Structures and Algorithms
    "cs:cs:DB",      # Databases
    "cs:cs:DC",      # Distributed, Parallel, and Cluster Computing
    "cs:cs:GT",      # Computer Science and Game Theory
    "cs:cs:MA",      # Multiagent Systems
    "cs:cs:RO",      # Robotics
    "cs:cs:SC",      # Symbolic Computation
    "cs:cs:SY",      # Systems and Control
    "cs:cs:AR",      # Hardware Architecture
    "cs:cs:CC",      # Computational Complexity
    "cs:cs:CG",      # Computational Geometry
    "cs:cs:CR",      # Cryptography and Security
    "cs:cs:CY",      # Computers and Society
    "cs:cs:DL",      # Digital Libraries
    "cs:cs:DM",      # Discrete Mathematics
    "cs:cs:ET",      # Emerging Technologies
    "cs:cs:FL",      # Formal Languages and Automata Theory
    "cs:cs:GL",      # General Literature
    "cs:cs:GR",      # Graphics
    "cs:cs:HC",      # Human-Computer Interaction
    "cs:cs:LO",      # Logic in Computer Science
    "cs:cs:MM",      # Multimedia
    "cs:cs:MS",      # Mathematical Software
    "cs:cs:NI",      # Networking and Internet Architecture
    "cs:cs:OH",      # Other Computer Science
    "cs:cs:OS",      # Operating Systems
    "cs:cs:PF",      # Performance
    "cs:cs:PL",      # Programming Languages
    "cs:cs:SD",      # Sound
    "cs:cs:SE",      # Software Engineering
    "cs:cs:SI",      # Social and Information Networks
    "cs:cs:OH",      # Other (catch-all)

    # Tier 3: Mathematics
    "math:math:CO",  # Combinatorics
    "math:math:DS",  # Dynamical Systems
    "math:math:FA",  # Functional Analysis
    "math:math:KT",  # K-Theory and Homology
    "math:math:LO",  # Logic
    "math:math:MP",  # Mathematical Physics
    "math:math:NT",  # Number Theory
    "math:math:OA",  # Operator Algebras
    "math:math:PR",  # Probability
    "math:math:QA",  # Quantum Algebra
    "math:math:RA",  # Rings and Algebra
    "math:math:RT",  # Representation Theory
    "math:math:SG",  # Symplectic Geometry
    "math:math:SP",  # Spectral Theory
    "math:math:ST",  # Statistics Theory
    "math:math:AC",  # Commutative Algebra
    "math:math:AG",  # Algebraic Geometry
    "math:math:AT",  # Algebraic Topology
    "math:math:CA",  # Classical Analysis
    "math:math:CT",  # Category Theory
    "math:math:CV",  # Complex Variables
    "math:math:DG",  # Differential Geometry
    "math:math:GN",  # General Topology
    "math:math:GR",  # Group Theory
    "math:math:GT",  # Geometric Topology
    "math:math:HO",  # History and Overview
    "math:math:MG",  # Metric Geometry
    "math:math:QA",  # Quantum Algebra

    # Tier 4: Statistics
    "stat:stat:AP",  # Applications
    "stat:stat:ME",  # Methodology
    "stat:stat:OT",  # Other
    "stat:stat:TH",  # Statistics Theory
]

# ─── FTS5 Schema (reusing arxiv_search.py)─────
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS arxiv_fts USING fts5(
    arxiv_id UNINDEXED,
    title,
    authors,
    abstract,
    categories UNINDEXED,
    doi UNINDEXED,
    journal_ref UNINDEXED,
    update_date UNINDEXED,
    tokenize='porter unicode61'
);
"""

META_SCHEMA = """
CREATE TABLE IF NOT EXISTS arxiv_meta (
    arxiv_id TEXT PRIMARY KEY,
    title TEXT,
    authors TEXT,
    abstract TEXT,
    categories TEXT,
    doi TEXT,
    journal_ref TEXT,
    update_date TEXT,
    imported_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_arxiv_meta_date ON arxiv_meta(update_date);
CREATE INDEX IF NOT EXISTS idx_arxiv_meta_cat ON arxiv_meta(categories);
CREATE INDEX IF NOT EXISTS idx_arxiv_meta_doi ON arxiv_meta(doi);
"""


# ════════════════════════════════════════════
# Database Layer
# ════════════════════════════════════════════


class ArxivMetaDB:
    """arXiv metadata SQLite storage (wrapper for arxiv_meta.db)"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA cache_size=-80000")  # 80MB cache
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(FTS_SCHEMA)
            conn.executescript(META_SCHEMA)
        logger.info(f"DB ready: {self.db_path}")

    def insert_batch(self, papers: list[tuple]):
        """Batch insert paper records"""
        with self._lock, self._conn() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO arxiv_meta
                   (arxiv_id, title, authors, abstract, categories,
                    doi, journal_ref, update_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                papers,
            )
            conn.executemany(
                """INSERT OR IGNORE INTO arxiv_fts
                   (arxiv_id, title, authors, abstract, categories,
                    doi, journal_ref, update_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                papers,
            )
            conn.commit()

    def count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM arxiv_meta").fetchone()[0]

    def exists(self, arxiv_id: str) -> bool:
        with self._conn() as conn:
            r = conn.execute(
                "SELECT 1 FROM arxiv_meta WHERE arxiv_id=?", (arxiv_id,)
            ).fetchone()
            return r is not None


# ════════════════════════════════════════════
# OAI-PMH Downloader
# ════════════════════════════════════════════


class OAIDownloader:
    """OAI-PMH downloader — supports resume, incremental updates, priority queue"""

    def __init__(self, db: ArxivMetaDB = None):
        self.db = db or ArxivMetaDB()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "HermesAgent/1.0 (mailto:lishen@example.com)"})
        self._last_request = 0.0
        self._stats = {"total_fetched": 0, "total_new": 0, "skipped": 0, "errors": 0}
        self._interrupted = False

    def _rate_limit(self):
        """arXiv recommends: 4 req/s peak + 1s sleep"""
        elapsed = time.time() - self._last_request
        if elapsed < RATE_LIMIT:
            time.sleep(RATE_LIMIT - elapsed)
        self._last_request = time.time()

    def _oai_request(self, params: dict) -> Optional[ET.Element]:
        """Send OAI-PMH request with retry support"""
        for attempt in range(MAX_RETRIES):
            self._rate_limit()
            try:
                resp = self.session.get(OAI_BASE, params=params, timeout=60)
                if resp.status_code == 503:
                    retry_after = int(resp.headers.get("Retry-After", 30))
                    logger.warning(f"  503 rate limited, waiting {retry_after}s...")
                    time.sleep(retry_after)
                    continue

                if resp.status_code != 200:
                    logger.warning(f"  HTTP {resp.status_code}, retry {attempt+1}/{MAX_RETRIES}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_BACKOFF[attempt])
                    continue

                root = ET.fromstring(resp.content)
                # Check errors
                error = root.find(".//{http://www.openarchives.org/OAI/2.0/}error")
                if error is not None:
                    code = error.get("code", "")
                    msg = error.text or ""
                    if code == "noRecordsMatch":
                        return None  # Normal: no more data
                    if code == "badResumptionToken":
                        logger.warning("  resumptionToken expired, restarting")
                        return None
                    logger.warning(f"  OAI error [{code}]: {msg}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_BACKOFF[attempt])
                    continue

                return root

            except (requests.RequestException, ET.ParseError) as e:
                logger.warning(f"  Request failed {params.get('verb', '?')}: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF[attempt])
                continue

        logger.error(f"  [{params.get('set', '?')}] Request ultimately failed")
        self._stats["errors"] += 1
        return None

    def _parse_record(self, record: ET.Element) -> Optional[tuple]:
        """Parse a single OAI-PMH record into a DB tuple

        Returns:
            tuple (arxiv_id, title, authors, abstract, categories, doi, journal_ref, update_date)
            or None (invalid record)
        """
        ns = {
            "oai": "http://www.openarchives.org/OAI/2.0/",
            "arxiv": "http://arxiv.org/OAI/arXiv/",
        }

        header = record.find(".//oai:header", ns)
        if header is not None and header.find("oai:status", ns) is not None:
            # Deleted record
            return None

        metadata = record.find(".//oai:metadata", ns)
        if metadata is None:
            return None

        # arXiv-specific metadata
        arxiv = metadata.find("arxiv:arXiv", ns)
        if arxiv is None:
            return None

        arxiv_id_el = arxiv.find("arxiv:id", ns)
        if arxiv_id_el is None or not arxiv_id_el.text:
            return None
        arxiv_id = arxiv_id_el.text.strip()
        # arXiv ID format: "0704.0001" or "math/0704001" (old format)
        # Keep only new format
        if not re.match(r"^\d{4}\.\d{4,5}(?:v\d+)?$", arxiv_id):
            # Strip version number and retry
            arxiv_id = arxiv_id.split("v")[0]
            if not re.match(r"^\d{4}\.\d{4,5}$", arxiv_id):
                return None

        def el_text(tag: str) -> str:
            el = arxiv.find(f"arxiv:{tag}", ns)
            return (el.text or "").strip()[:500] if el is not None else ""

        title = el_text("title")
        authors = el_text("authors")
        abstract = el_text("abstract")
        categories = el_text("categories")

        doi = ""
        doi_el = arxiv.find("arxiv:doi", ns)
        if doi_el is not None and doi_el.text:
            doi = doi_el.text.strip()

        journal_ref = ""
        jr_el = arxiv.find("arxiv:journal_ref", ns)
        if jr_el is not None and jr_el.text:
            journal_ref = jr_el.text.strip()[:200]

        update_date = ""
        version = arxiv.find("arxiv:version", ns)
        if version is not None:
            date_el = version.find("arxiv:date", ns)
            if date_el is not None and date_el.text:
                update_date = date_el.text[:10]  # YYYY-MM-DD

        if not title:
            return None

        return (arxiv_id, title[:500], authors[:500], abstract[:2000],
                categories, doi, journal_ref, update_date)

    def download_category(self, set_spec: str, from_date: str = "", to_date: str = "", max_pages: int = 0) -> int:
        """Download all/incremental records for one category

        Args:
            set_spec: Category identifier, e.g. 'cs:cs:AI'
            from_date: Start date YYYY-MM-DD, empty for all
            to_date: End date, empty for today
            max_pages: Max pages, 0=unlimited

        Returns:
            Number of new records added
        """
        new_count = 0
        page = 0
        resumption_token = None

        params = {
            "verb": "ListRecords",
            "metadataPrefix": "arXiv",
            "set": set_spec,
        }
        if from_date:
            params["from"] = from_date
        if to_date:
            params["until"] = to_date

        while not self._interrupted:
            page += 1
            if max_pages > 0 and page > max_pages:
                break

            if resumption_token:
                params = {
                    "verb": "ListRecords",
                    "resumptionToken": resumption_token,
                }

            root = self._oai_request(params)
            if root is None:
                break  # noRecordsMatch or error

            # Parse records
            records = root.findall(".//{http://www.openarchives.org/OAI/2.0/}record")
            if not records:
                break

            batch = []
            for record in records:
                parsed = self._parse_record(record)
                if parsed:
                    arxiv_id = parsed[0]
                    if not self.db.exists(arxiv_id):
                        batch.append(parsed)
                    else:
                        self._stats["skipped"] += 1

                    if len(batch) >= BATCH_WRITE:
                        self.db.insert_batch(batch)
                        new_count += len(batch)
                        batch = []

                    self._stats["total_fetched"] += 1

            if batch:
                self.db.insert_batch(batch)
                new_count += len(batch)

            # resumptionToken
            token_el = root.find(".//{http://www.openarchives.org/OAI/2.0/}resumptionToken")
            if token_el is not None and token_el.text:
                resumption_token = token_el.text
                cursor = int(token_el.get("cursor", 0))
                total = int(token_el.get("completeListSize", 0))
                logger.info(
                    f"  [{set_spec}] page {page}: +{new_count} "
                    f"(cursor: {cursor:,}/{total:,})"
                )
            else:
                logger.info(f"  [{set_spec}] Complete: +{new_count} new papers")
                break

        return new_count

    def download_priority(self, from_date: str = "", incremental: bool = False):
        """Download all categories by priority

        Args:
            from_date: YYYY-MM-DD, empty for all
            incremental: Incremental mode, auto-calculate from_date
        """
        if incremental:
            # Get the date of the last paper downloaded
            state = self._load_state()
            last_date = state.get("last_completed_date", "")
            if last_date:
                from_date = last_date
                logger.info(f"Incremental mode, starting from {from_date}")

        total_new = 0
        total_time = 0.0
        total_skipped = 0

        start_all = time.time()

        for idx, set_spec in enumerate(DOWNLOAD_PRIORITIES):
            logger.info(f"\n[{idx+1}/{len(DOWNLOAD_PRIORITIES)}] 📥 {set_spec}")

            set_start = time.time()
            new_count = self.download_category(set_spec, from_date=from_date)
            elapsed = time.time() - set_start

            total_new += new_count
            total_time += elapsed
            total_skipped += self._stats["skipped"]

            if new_count > 0:
                rate = new_count / elapsed if elapsed > 0 else 0
                logger.info(f"  → {new_count} papers in {elapsed:.1f}s ({rate:.0f}/s)")

            # Save progress (resume)
            self._save_state({
                "last_set": set_spec,
                "completed_sets": idx + 1,
                "total_sets": len(DOWNLOAD_PRIORITIES),
                "total_new": total_new,
                "last_completed_date": from_date or datetime.now().strftime("%Y-%m-%d"),
                "updated_at": datetime.now().isoformat(),
            })

            if self._interrupted:
                logger.warning("⚠️ Interrupted, stopping download")
                break

        all_elapsed = time.time() - start_all
        total_in_db = self.db.count()

        logger.info(f"\n{'='*50}")
        logger.info("✅ Download complete")
        logger.info(f"  New: {total_new} papers")
        logger.info(f"  Total: {total_in_db:,} papers")
        logger.info(f"  Time: {all_elapsed:.0f}s")

        return total_new

    def _save_state(self, state: dict):
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def _load_state(self) -> dict:
        if STATE_PATH.exists():
            with open(STATE_PATH) as f:
                return json.load(f)
        return {}

    def print_status(self):
        """Print download status"""
        total = self.db.count()
        state = self._load_state()

        print("\n📊 arXiv OAI-PMH Download Status")
        print(f"  DB total papers: {total:,}")
        print(f"  Last updated:    {state.get('updated_at', 'never')}")
        print(f"  Progress:        {state.get('completed_sets', 0)}/{state.get('total_sets', 0)} categories")
        print(f"  New this run:    {state.get('total_new', 0)} papers")
        print(f"  Last category:   {state.get('last_set', 'N/A')}")
        print(f"  Last date:       {state.get('last_completed_date', 'N/A')}")
        print(f"\n  DB path: {self.db.db_path}")
        print(f"  State file: {STATE_PATH}")

    def interrupt(self):
        self._interrupted = True


# ════════════════════════════════════════════
# CLI Entry
# ════════════════════════════════════════════


def main():
    import argparse

    parser = argparse.ArgumentParser(description="arXiv OAI-PMH metadata downloader")
    parser.add_argument("--all", action="store_true", help="Full download of all categories")
    parser.add_argument("--incremental", action="store_true", help="Incremental update (last 1 day)")
    parser.add_argument("--set", "-s", type=str, default="", help="Download specific category")
    parser.add_argument("--from-date", "-f", type=str, default="", help="Start date YYYY-MM-DD")
    parser.add_argument("--status", action="store_true", help="View download status")
    parser.add_argument("--background", action="store_true", help="Background mode (catch SIGINT)")
    parser.add_argument("--tier1-only", action="store_true", help="Download Tier 1 only (AI/ML/PDE core)")

    args = parser.parse_args()

    db = ArxivMetaDB()
    downloader = OAIDownloader(db=db)

    if args.status:
        downloader.print_status()
        return

    # Register SIGINT handler
    import signal
    def _on_sigint(sig, frame):
        logger.warning("\n⚠️ Received Ctrl+C, saving progress and exiting...")
        downloader.interrupt()
    signal.signal(signal.SIGINT, _on_sigint)

    if args.set:
        logger.info(f"Downloading category: {args.set}")
        downloader.download_category(args.set, from_date=args.from_date)
    elif args.incremental:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info(f"Incremental update (since {yesterday})")
        downloader.download_priority(from_date=yesterday, incremental=True)
    elif args.tier1_only:
        logger.info("Downloading Tier 1 core categories only")
        global DOWNLOAD_PRIORITIES
        DOWNLOAD_PRIORITIES = DOWNLOAD_PRIORITIES[:11]  # First 11 are Tier 1
        downloader.download_priority(from_date=args.from_date)
    elif args.all:
        logger.info("Full download of all categories (by priority)")
        downloader.download_priority(from_date=args.from_date)
    else:
        parser.print_help()
        print("\nRecommended usage:")
        print("  # Background full download")
        print("  nohup python scripts/download_arxiv_oai.py --all > download.log 2>&1 &")
        print("  # Or download core categories")
        print("  python scripts/download_arxiv_oai.py --tier1-only")
        print("  # Daily incremental update (crontab)")
        print("  0 6 * * * cd ... && python scripts/download_arxiv_oai.py --incremental")
        print("  # Check status")
        print("  python scripts/download_arxiv_oai.py --status")


if __name__ == "__main__":
    main()
