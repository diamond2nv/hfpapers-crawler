# Distributed Deployment Guide

# Prerequisites:
# - GPU Server (nautilus / ${SERVER_HOST}) — primary workhorse
# - CPU Server — lightweight crawl node
# - Local machine (macOS/Ubuntu) — development + testing

# ─── 1. Install Dependencies ───────────────────────────

#    On all machines:
#   cd ~/Gitlab/Agentic4Sci/hfpapers-clawler
#   pip install -e ".[scrapy]"
#   pip install scrapy-redis  # Distributed-only

# ─── 2. Choose Redis Host ─────────────────────

#   Plan A: Lightweight Redis on the GPU server
#     sudo apt install redis-server  (if you have sudo)
#     or: pip install valkey
#     redis-server --port 16379 --daemonize yes

#   Plan B: Reuse existing Redis (e.g., if already installed)

#   Plan C: No Redis — Shared JSON mode
#     Each machine runs independently with no queue sharing.
#     Only shared dedup file is synced via NFS/scp/git.
#     Dedup file: ~/wiki/raw/papers/hfpapers-crawled.json

# ─── 3. Start on Each Machine ──────────────────────────

#   GPU Server (heavy search + paper download):
#     hfpclawer search --max-pages 5

#   CPU Server (arXiv search + verification):
#     hfpclawer search --max-pages 3

#   Local machine (testing + OpenReview search):
#     hfpclawer search --max-pages 2

#   Distributed mode (requires Redis):
#     scrapy crawl multi_source -s REDIS_URL=redis://192.168.1.100:16379

# ─── 4. View Results ────────────────────────────

#   All machines share the same output paths:
#     data/candidates_latest.json    ← Latest candidate list
#     pdfs/                          ← PDF files
#     mds/                           ← MD extraction files
#     ~/wiki/raw/papers/             ← Global dedup records

# ─── 5. Anti-Crawl Config ──────────────────────

#   Configure each machine independently via config.yaml:

#   Machine A (IP 1):
#     download_delay: 3.0
#     randomize_download_delay: true
#     random_ua_pool: ["Mozilla/5.0 (X11; Linux x86_64)...", ...]

#   Machine B (IP 2):
#     download_delay: 2.0
#     randomize_download_delay: true
#     random_ua_pool: ["Mozilla/5.0 (Macintosh; Intel Mac OS X)...", ...]

#   This ensures each machine egresses from a different IP,
#   and each request rotates User-Agent.

# ─── 6. Fault Recovery ────────────────────────────

#   After interruption, scrapy-redis will:
#     1. Resume incomplete request queue from Redis
#     2. Skip already-deduped requests
#     3. Skip PDF/MD files already in data directory
#
#   No manual recovery needed.
