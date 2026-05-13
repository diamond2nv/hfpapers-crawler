#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hfpclawer -- Multi-source academic paper crawler -- download pipeline

Provides unified download pipeline: OAI-PMH incremental/full download + resume + background monitoring.
"""

from hfpclawer.download.base import BaseDownloader
from hfpclawer.download.kaggle import KaggleDownloader
from hfpclawer.download.monitor import MonitorDaemon
from hfpclawer.download.oai import OaiPmhDownloader
from hfpclawer.download.resume import ResumeState

__all__ = [
    "BaseDownloader",
    "ResumeState",
    "OaiPmhDownloader",
    "KaggleDownloader",
    "MonitorDaemon",
]
