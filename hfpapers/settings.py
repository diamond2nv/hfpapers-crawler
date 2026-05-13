#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# settings.py
import os

BOT_NAME = "hfpapers"

SPIDER_MODULES = ["hfpapers.spiders"]
NEWSPIDER_MODULE = "hfpapers.spiders"

# ─── Anti-crawl Configuration ─────────────────────────────
# Loaded from config.yaml anti_crawl section (hardcoded defaults below)

# Respect robots.txt (basic etiquette)
ROBOTSTXT_OBEY = True

# Concurrency control
CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 2  # Per-domain limit

# Download delay (RandomDelayMiddleware applies ±50% jitter on top)
DOWNLOAD_DELAY = 2.0
RANDOMIZE_DOWNLOAD_DELAY = False    # Our own middleware handles randomization

# Download timeout (prevent hanging)
DOWNLOAD_TIMEOUT = 30

# ─── Middleware Chain (execution order: lower numbers execute first) ─────
DOWNLOADER_MIDDLEWARES = {
    # Built-in middlewares
    "scrapy.downloadermiddlewares.robotstxt.RobotsTxtMiddleware": 100,
    "scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware": 750,
    # Custom middlewares
    "hfpapers.middlewares.RandomUserAgentMiddleware": 200,
    "hfpapers.middlewares.RandomDelayMiddleware": 250,
    "hfpapers.middlewares.ProxyMiddleware": 350,
    "hfpapers.middlewares.CookiesPoolMiddleware": 400,
    "hfpapers.middlewares.IntelligentRetryMiddleware": 500,
    "hfpapers.middlewares.RobustDownloaderMiddleware": 510,
}

# ─── Deduplication ───────────────────────────────────
# Standalone mode: default RFPDupeFilter
# Distributed mode: uses scrapy-redis (see settings_redis.py)
DUPEFILTER_CLASS = "scrapy.dupefilters.RFPDupeFilter"
DUPEFILTER_DEBUG = True

# ─── Pipeline ───────────────────────────────
ITEM_PIPELINES = {
    "hfpapers.pipelines.StorePipeline": 100,    # Write to SQLite + cross-validate
    "hfpapers.pipelines.ClassifyPipeline": 200, # Relevance classification
    "hfpapers.pipelines.ExportPipeline": 300,   # Export candidate list
    "hfpapers.pipelines.DownloadPipeline": 400, # PDF download + MD conversion
}

# ─── Crawl Extensions ───────────────────────────────
EXTENSIONS = {
    "scrapy.extensions.telnet.TelnetConsole": None,  # Disable telnet
}

# ─── Output Directories ───────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
PDF_DIR = os.path.join(PROJECT_ROOT, "pdfs")
MD_DIR = os.path.join(PROJECT_ROOT, "mds")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")

for d in [DATA_DIR, PDF_DIR, MD_DIR, LOG_DIR]:
    os.makedirs(d, exist_ok=True)

# Crawled records path
CRAWLED_JSON = os.path.expanduser("~/wiki/raw/papers/hfpapers-crawled.json")

# ─── Logging ───────────────────────────────────
LOG_ENABLED = True
LOG_FILE = os.path.join(LOG_DIR, "spider.log")
LOG_LEVEL = "INFO"

# ─── User-Agent (default, overwritten by middleware) ───────
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
