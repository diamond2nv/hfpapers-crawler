# Docker Deployment Guide

Containerize hfpclawer for reproducible deployment and easy distributed setup.

## Why Docker?

| Benefit | Details |
|---------|---------|
| **Environment isolation** | System deps (Chrome, Playwright, nss) bundled once |
| **Reproducible** | Same image runs identically on any machine |
| **Distributed ready** | `docker-compose up` on both servers, zero config diff |
| **Resource control** | `--memory=2g --cpus=2` for precise limits |

## Prerequisites

**Important**: If you don't have sudo, use rootless Docker:

```bash
# Check if Docker is available
docker info --format '{{.ServerVersion}}'

# If not, install rootless
curl -fsSL https://get.docker.com/rootless | sh
export PATH=/home/$USER/bin:$PATH
docker info
```

Or use conda/podman as alternatives.

## Dockerfile

```dockerfile
FROM python:3.11-slim

# System deps for Playwright/Chrome
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates fonts-liberation \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install hfpclawer with all extras
RUN pip install --no-cache-dir "hfpclawer[scrapy,llm,pdf]"

# Config & data volumes
VOLUME ["/app/config", "/app/data", "/app/downloads"]

# MCP server (default)
EXPOSE 8765

ENTRYPOINT ["hfpclawer"]
CMD ["mcp"]
```

Build:

```bash
docker build -t hfpclawer .
```

## docker-compose.yml (Single Server)

```yaml
version: '3.8'
services:
  crawler:
    image: hfpclawer
    restart: unless-stopped
    ports: ["8765:8765"]
    environment:
      - HF_TOKEN=${HF_TOKEN}
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./downloads:/app/downloads
    command: ["mcp", "--port", "8765"]
```

## docker-compose.yml (Distributed, Two Servers)

On **Server A** (with Redis):

```yaml
version: '3.8'
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    ports: ["6379:6379"]
    volumes: [redis_data:/data]

  crawler:
    image: hfpclawer
    restart: unless-stopped
    depends_on: [redis]
    environment:
      - HF_TOKEN=${HF_TOKEN}
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./downloads:/app/downloads
    command: ["crawl", "arxiv"]

volumes:
  redis_data:
```

On **Server B** (no Redis):

```yaml
version: '3.8'
services:
  crawler:
    image: hfpclawer
    restart: unless-stopped
    environment:
      - HF_TOKEN=${HF_TOKEN}
      - REDIS_URL=redis://192.168.1.100:6379  # A's IP
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./downloads:/app/downloads
    command: ["crawl", "arxiv"]
```

## Usage

```bash
# Single server MCP
docker compose up -d
docker compose logs -f

# Distributed
docker compose -f docker-compose.dist.yml up -d

# Run one-off commands
docker run --rm -it hfpclawer search --max-pages 1
```

## Data Persistence

| Path | Content | Recommendation |
|------|---------|---------------|
| `./config/` | config.yaml, .env | Git-tracked |
| `./data/` | arxiv_meta.db, crawled.json | Volume mount |
| `./downloads/` | PDFs, MDS | Volume mount |

For shared storage across servers, use NFS or S3:

```yaml
volumes:
  downloads:
    driver_opts:
      type: nfs
      o: addr=192.168.1.100,rw
      device: :/mnt/nfs/downloads
```

## Limitations

- **No sudo?** Use rootless Docker (`dockerd-rootless-setuptool.sh install`)
- **GPU?** Not needed for crawling, but add `runtime: nvidia` for LLM inference
- **Network?** Container's `localhost` is isolated — use host IP or Docker network names

## Docker vs Host

| Aspect | Docker | Host (venv) |
|--------|--------|-------------|
| Setup time | ~2 min (first build) | ~30 sec (pip install) |
| Isolation | Full | Partial |
| Distributed | docker-compose | scrapy-redis + manual |
| Disk usage | ~500 MB image | ~100 MB venv |
| Restart policy | Built-in | systemd/supervisord |
