"""MonitorDaemon — 后台守护进程，定时轮询 OAI-PMH 增量下载

纯 Python 实现，不依赖 systemd/crontab。
PID 文件 + 15 分钟轮询 + RotatingFileHandler 日志。
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

# ─── 默认路径 ───────────────────────────────
PID_FILE = "data/monitor.pid"
LOG_FILE = "data/monitor.log"
POLL_INTERVAL = 900  # 15 分钟


class MonitorDaemon:
    """后台监控守护

    用法:
        daemon = MonitorDaemon()
        daemon.start()     # fork 后台进程
        daemon.stop()      # kill 后台进程
        daemon.status()    # 检查状态
    """

    def __init__(self, base_dir: str = "", interval: int = POLL_INTERVAL):
        self.base_dir = Path(base_dir).expanduser() if base_dir else Path.cwd()
        self.pid_path = self.base_dir / PID_FILE
        self.log_path = self.base_dir / LOG_FILE
        self.interval = interval
        self._running = False

    def _setup_logging(self):
        """守护进程独立日志"""
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
        """守护进程主循环"""
        self._running = True

        def _sigterm(sig, frame):
            logger.info("收到 SIGTERM，退出...")
            self._running = False

        signal.signal(signal.SIGTERM, _sigterm)
        signal.signal(signal.SIGINT, _sigterm)

        logger.info(f"MonitorDaemon 启动 (PID={os.getpid()}, interval={self.interval}s)")
        logger.info(f"日志: {self.log_path}")

        while self._running:
            try:
                logger.info(f"开始轮询 ({datetime.now().isoformat()})")
                downloader = OaiPmhDownloader()
                downloader.run(incremental=True)
                logger.info(f"轮询完成, 等待 {self.interval}s...")
            except Exception as e:
                logger.error(f"轮询失败: {e}")

            # 分片睡眠，以便响应 SIGTERM
            for _ in range(self.interval // 5):
                if not self._running:
                    break
                time.sleep(5)

        logger.info("MonitorDaemon 已退出")

    def start(self):
        """启动后台守护进程"""
        if self.is_running():
            pid = self._read_pid()
            logger.warning(f"MonitorDaemon 已在运行 (PID={pid})")
            return False

        pid = os.fork()
        if pid > 0:
            # 父进程
            logger.info(f"MonitorDaemon 已启动 (PID={pid})")
            return True

        # 子进程
        os.setsid()
        sys.stdout.flush()
        sys.stderr.flush()

        # 重定向 stdin/stdout/stderr
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.close(devnull)

        self._write_pid()
        self._setup_logging()
        self._loop()

    def stop(self):
        """停止守护进程"""
        pid = self._read_pid()
        if pid is None:
            logger.warning("MonitorDaemon 未运行")
            return False

        try:
            os.kill(pid, signal.SIGTERM)
            # 等待进程退出
            for _ in range(10):
                try:
                    os.kill(pid, 0)
                    time.sleep(0.5)
                except OSError:
                    break
            self._remove_pid()
            logger.info(f"MonitorDaemon 已停止 (PID={pid})")
            return True
        except OSError:
            self._remove_pid()
            logger.warning("MonitorDaemon 进程已不存在")
            return False

    def is_running(self) -> bool:
        """检查是否在运行"""
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
        """查看状态"""
        running = self.is_running()
        result = {
            "running": running,
            "pid": self._read_pid(),
            "pid_file": str(self.pid_path),
            "log_file": str(self.log_path),
            "interval": self.interval,
        }
        if running:
            # 读取下载状态
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
