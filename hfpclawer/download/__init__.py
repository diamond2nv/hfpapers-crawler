"""hfpclawer -- Multi-source academic paper crawler -- download pipeline

提供统一下载管道：OAI-PMH 增量/全量下载 + 断点续传 + 后台监控。
"""

from hfpclawer.download.base import BaseDownloader
from hfpclawer.download.resume import ResumeState
from hfpclawer.download.oai import OaiPmhDownloader
from hfpclawer.download.kaggle import KaggleDownloader
from hfpclawer.download.monitor import MonitorDaemon

__all__ = [
    "BaseDownloader",
    "ResumeState",
    "OaiPmhDownloader",
    "KaggleDownloader",
    "MonitorDaemon",
]
