#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Distributed deployment configuration

Usage:
  # Standalone (default)
  scrapy crawl multi_source

  # Distributed (requires Redis + scrapy-redis)
  scrapy crawl multi_source -s SETTINGS_MODULE=hfpapers.settings_redis

Install code on both GPU/CPU servers and laptops,
set the redis address in .env to share the deduplication queue.
"""

import os

# Inherit base configuration
from hfpapers.settings import *  # noqa: F401, F403

# ─── Redis Configuration ─────────────────────────────
# Requires: pip install scrapy-redis

# Shared deduplication
DUPEFILTER_CLASS = "scrapy_redis.dupefilter.RFPDupeFilter"
SCHEDULER = "scrapy_redis.scheduler.Scheduler"
SCHEDULER_PERSIST = True  # Keep queue after crawl, resume next time

# Redis connection (from config.yaml or environment variables)
REDIS_HOST = os.environ.get("SCRAPY_REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("SCRAPY_REDIS_PORT", 6379))
REDIS_PARAMS = {
    "host": REDIS_HOST,
    "port": REDIS_PORT,
    "password": os.environ.get("SCRAPY_REDIS_PASSWORD", ""),
    "db": int(os.environ.get("SCRAPY_REDIS_DB", 0)),
}

# Queue key prefix
SCHEDULER_QUEUE_KEY = "hfpapers:requests"
SCHEDULER_DUPEFILTER_KEY = "hfpapers:dupefilter"
SCHEDULER_SERIALIZER = "scrapy_redis.serializer.JsonSerializer"

# ─── Distributed deduplication: also write to shared JSON ───────────
ITEM_PIPELINES = {
    "hfpapers.pipelines.DedupPipeline": 100,
    "hfpapers.pipelines.ArxivVerifyPipeline": 150,
    "hfpapers.pipelines.ClassifyPipeline": 200,
    "hfpapers.pipelines.ExportPipeline": 300,
    "hfpapers.pipelines.DownloadPipeline": 400,
}
