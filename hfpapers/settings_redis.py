"""
分布式部署配置文件

用法:
  # 单机（默认）
  scrapy crawl multi_source

  # 分布式（需要 Redis，且安装 scrapy-redis）
  scrapy crawl multi_source -s SETTINGS_MODULE=hfpapers.settings_redis

在 GPU/CPU 服务器和笔记本上各安装一份代码，
改 .env 里的 redis 地址即可共享去重队列。
"""

import os
import sys

# 继承基础配置
from hfpapers.settings import *  # noqa: F401, F403

# ─── Redis 配置 ─────────────────────────────
# 需要安装: pip install scrapy-redis

# 共享去重
DUPEFILTER_CLASS = "scrapy_redis.dupefilter.RFPDupeFilter"
SCHEDULER = "scrapy_redis.scheduler.Scheduler"
SCHEDULER_PERSIST = True  # 爬取结束后不清空队列，下次续爬

# Redis 连接（从 config.yaml 或环境变量读取）
REDIS_HOST = os.environ.get("SCRAPY_REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("SCRAPY_REDIS_PORT", 6379))
REDIS_PARAMS = {
    "host": REDIS_HOST,
    "port": REDIS_PORT,
    "password": os.environ.get("SCRAPY_REDIS_PASSWORD", ""),
    "db": int(os.environ.get("SCRAPY_REDIS_DB", 0)),
}

# 队列KEY前缀
SCHEDULER_QUEUE_KEY = "hfpapers:requests"
SCHEDULER_DUPEFILTER_KEY = "hfpapers:dupefilter"
SCHEDULER_SERIALIZER = "scrapy_redis.serializer.JsonSerializer"

# ─── 分布式去重: 也写入共享 JSON ───────────
ITEM_PIPELINES = {
    "hfpapers.pipelines.DedupPipeline": 100,
    "hfpapers.pipelines.ArxivVerifyPipeline": 150,
    "hfpapers.pipelines.ClassifyPipeline": 200,
    "hfpapers.pipelines.ExportPipeline": 300,
    "hfpapers.pipelines.DownloadPipeline": 400,
}
