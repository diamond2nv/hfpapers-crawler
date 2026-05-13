# Distributed Scrapy Deployment Guide

Use `scrapy-redis` to run hfpclawer spiders across two SSH servers with shared queue and dedup.

## Architecture

```
┌─────────────┐     ┌──────────────┐
│  Server A    │     │  Server B    │
│  Scrapy      │     │  Scrapy      │
│  Spider 1..N │     │  Spider 1..N │
└──────┬───────┘     └──────┬────────┘
       │                    │
       └────────┬───────────┘
                ▼
        ┌───────────────┐
        │  Redis (Queue  │
        │  + DupeFilter) │
        │  Run on A      │
        └───────────────┘
```

## Prerequisites

- Both servers have SSH access to each other
- Python 3.10+ with `pip install hfpclawer[scrapy]` on both
- Redis installed on Server A (or a dedicated machine)

## Step 1: Install Redis on Server A

```bash
# No sudo? Use conda or compile from source
conda install -c conda-forge redis-server

# Or via pip (lightweight alternative)
pip install redis

# Start Redis (custom port to avoid conflicts)
redis-server --port 16379 --daemonize yes
```

Check: `redis-cli -p 16379 ping` → `PONG`

## Step 2: Configure Spider Settings

Edit your spider's `settings.py` (or pass via env):

```python
# settings.py
SCHEDULER = "scrapy_redis.scheduler.Scheduler"
DUPEFILTER_CLASS = "scrapy_redis.dupefilter.RFPDupeFilter"
SCHEDULER_PERSIST = True  # Keep queue between runs

# Point to Redis on Server A
REDIS_URL = "redis://192.168.1.100:16379"  # Replace with A's IP

# Rate limiting — each spider independently respects this
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 4
DOWNLOAD_DELAY = 1.0
RANDOMIZE_DOWNLOAD_DELAY = True
```

## Step 3: Run on Both Servers

```bash
# Server A (also hosts Redis)
cd /path/to/hfpapers-crawler
hfpclawer crawl arxiv        # Starts spider, pulls from shared queue

# Server B (SSH from A or directly)
ssh user@server-b "cd /path/to/hfpapers-crawler && hfpclawer crawl arxiv"
```

Both spiders share the same request queue and dedup set via Redis.

## Step 4: Monitor Progress

```bash
# Check queue size
redis-cli -p 16379 LLEN hfpclawer:requests

# Check dedup count
redis-cli -p 16379 SCARD hfpclawer:dupefilter

# Flush queue (reset)
redis-cli -p 16379 FLUSHDB
```

## Notes

| Concern | Solution |
|---------|----------|
| **Dedup across restarts** | `SCHEDULER_PERSIST = True` keeps Redis state |
| **Rate limiting** | Each spider respects its own `DOWNLOAD_DELAY` + `CONCURRENT_REQUESTS` |
| **File storage** | PDFs/MDs go to local disk on each server — use NFS/S3 for shared storage |
| **Log centralization** | Set `LOG_FILE` per server with hostname in filename: `logs/arxiv_serverA.log` |
| **Graceful stop** | `scrapy crawl arxiv -s JOBDIR=crawls/arxiv` — supports pause/resume |

## Graceful Shutdown

```bash
# Pause: just Ctrl+C or kill -TERM
# Resume: restart with same JOBDIR
scrapy crawl arxiv -s JOBDIR=crawls/arxiv
```

Or via Redis:

```bash
# Drain queue without dropping requests
redis-cli -p 16379 LTRIM hfpclawer:requests 0 -1
```

## Troubleshooting

### Redis connection refused
- Check firewall: `sudo ufw status` (if you have sudo)
- Or use SSH tunnel: `ssh -L 16379:localhost:16379 server-a`

### Duplicate requests across spiders
- Normal — scrapy-redis ensures no double-crawl via shared dupefilter
- Ensure `SCHEDULER_PERSIST = True` on ALL spiders

### Database conflicts
- Each spider writes to its own SQLite by default
- For shared DB: use MariaDB/PostgreSQL, or set `db.path` to the same NFS path
- **Caveat**: SQLite is not safe for concurrent writes — switch to a proper DB for production

## References

- [scrapy-redis docs](https://github.com/rmax/scrapy-redis)
- [Scrapy distributed crawling best practices](https://docs.scrapy.org/en/latest/topics/practices.html#distributed-crawls)
