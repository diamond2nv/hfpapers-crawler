#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MonitorDaemon — Background daemon, periodic OAI-PMH incremental download

Pure Python implementation, no systemd/crontab dependency.
PID file + 15-min polling + RotatingFileHandler logging.
"""

import logging
import os
import signal
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from hfpclawer.download.oai import OaiPmhDownloader

logger = logging.getLogger("hfpclawer.download.monitor")

# ─── Default paths ───────────────────────────────
PID_FILE = "data/monitor.pid"
LOG_FILE = "data/monitor.log"
POLL_INTERVAL = 900  # 15 minutes


class MonitorDaemon:
    """Background monitor daemon

    Usage:
        daemon = MonitorDaemon()
        daemon.start()     # fork background process
        daemon.stop()      # kill background process
        daemon.status()    # check status
    """

    def __init__(self, base_dir: str = "", interval: int = POLL_INTERVAL):
        self.base_dir = Path(base_dir).expanduser() if base_dir else Path.cwd()
        self.pid_path = self.base_dir / PID_FILE
        self.log_path = self.base_dir / LOG_FILE
        self.interval = interval
        self._running = False

    def _setup_logging(self):
        """Daemon standalone log"""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            str(self.log_path), maxBytes=10 * 1024 * 1024, backupCount=5,
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logging.getLogger("hfpclawer").addHandler(handler)
        logging.getLogger("hfpclawer").setLevel(logging.INFO)

    def _write_pid(self):
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.pid_path, "w") as f:
            f.write(str(os.getpid()))

    def _loop(self):
        """Daemon main loop"""
        self._running = True

        def _sigterm(sig, frame):
            logger.info("Received SIGTERM, exiting...")
            self._running = False

        signal.signal(signal.SIGTERM, _sigterm)
        signal.signal(signal.SIGINT, _sigterm)

        logger.info(f"MonitorDaemon started (PID={os.getpid()}, interval={self.interval}s)")
        logger.info(f"Log: {self.log_path}")

        while self._running:
            try:
                logger.info(f"Starting poll ({datetime.now().isoformat()})")
                downloader = OaiPmhDownloader()
                downloader.run(incremental=True)
                logger.info(f"Poll complete, waiting {self.interval}s...")
            except Exception as e:
                logger.error(f"Poll failed: {e}")

            # Sliced sleep to respond to SIGTERM
            for _ in range(self.interval // 5):
                if not self._running:
                    break
                time.sleep(5)

        logger.info("MonitorDaemon exited")

    def start(self):
        """Start background daemon"""
        if self.is_running():
            pid = self._read_pid()
            logger.warning(f"MonitorDaemon already running (PID={pid})")
            return False

        pid = os.fork()
        if pid > 0:
            # Parent process
            logger.info(f"MonitorDaemon started (PID={pid})")
            return True

        # Child process
        os.setsid()
        sys.stdout.flush()
        sys.stderr.flush()

        # Redirect stdin/stdout/stderr
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.close(devnull)

        self._write_pid()
        self._setup_logging()
        self._loop()

    def stop(self):
        """Stop daemon"""
        pid = self._read_pid()
        if pid is None:
            logger.warning("MonitorDaemon not running")
            return False

        try:
            os.kill(pid, signal.SIGTERM)
            # Wait for process to exit
            for _ in range(10):
                try:
                    os.kill(pid, 0)
                    time.sleep(0.5)
                except OSError:
                    break
            self._remove_pid()
            logger.info(f"MonitorDaemon stopped (PID={pid})")
            return True
        except OSError:
            self._remove_pid()
            logger.warning("MonitorDaemon process no longer exists")
            return False

    def is_running(self) -> bool:
        """Check if running"""
        pid = self._read_pid()
        if pid is None:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            self._remove_pid()
            return False

    def status(self) -> dict:
        """View status"""
        running = self.is_running()
        result = {
            "running": running,
            "pid": self._read_pid(),
            "pid_file": str(self.pid_path),
            "log_file": str(self.log_path),
            "interval": self.interval,
        }
        if running:
            # Read download state
            try:
                from hfpapers.config import get as cfg_get
                from hfpclawer.download.base import ResumeState
                base = Path(__file__).resolve().parent.parent.parent
                db_path = str(base / cfg_get("db.path", "data/arxiv_meta.db"))
                state = ResumeState(db_path, "oai").get()
                result["download_state"] = state
            except Exception as e:
                result["download_state"] = {"error": str(e)}
        return result

    def _read_pid(self) -> Optional[int]:
        if self.pid_path.exists():
            try:
                with open(self.pid_path) as f:
                    return int(f.read().strip())
            except (ValueError, OSError):
                return None
        return None

    def _remove_pid(self):
        if self.pid_path.exists():
            self.pid_path.unlink()
