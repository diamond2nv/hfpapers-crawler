# Docker 部署指南

将 hfpclawer 容器化以实现可复现的部署和简单的分布式设置。

## 为什么用 Docker？

| 优势 | 详情 |
|------|------|
| **环境隔离** | 系统依赖（Chrome、Playwright、nss）一次性打包 |
| **可复现** | 同一镜像在任何机器上运行一致 |
| **分布式就绪** | `docker-compose up` 在双服务器上，零配置差异 |
| **资源控制** | `--memory=2g --cpus=2` 精确限制资源 |

## 前置条件

**重要**: 如果没有 sudo，请使用 rootless Docker：

```bash
# 检查 Docker 是否可用
docker info --format '{{.ServerVersion}}'

# 如果不可用，安装 rootless
curl -fsSL https://get.docker.com/rootless | sh
export PATH=/home/$USER/bin:$PATH
docker info
```

或者使用 conda/podman 作为替代方案。

## Dockerfile

```dockerfile
FROM python:3.11-slim

# Playwright/Chrome 的系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates fonts-liberation \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 hfpclawer 含所有额外功能
RUN pip install --no-cache-dir "hfpclawer[scrapy,llm,pdf]"

# 配置和数据卷
VOLUME ["/app/config", "/app/data", "/app/downloads"]

# MCP 服务器（默认）
EXPOSE 8765

ENTRYPOINT ["hfpclawer"]
CMD ["mcp"]
```

构建：

```bash
docker build -t hfpclawer .
```

## docker-compose.yml（单服务器）

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

## docker-compose.yml（分布式，双服务器）

**服务器 A**（运行 Redis）：

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

**服务器 B**（无 Redis）：

```yaml
version: '3.8'
services:
  crawler:
    image: hfpclawer
    restart: unless-stopped
    environment:
      - HF_TOKEN=${HF_TOKEN}
      - REDIS_URL=redis://192.168.1.100:6379  # A 的 IP
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./downloads:/app/downloads
    command: ["crawl", "arxiv"]
```

## 使用方法

```bash
# 单服务器 MCP
docker compose up -d
docker compose logs -f

# 分布式
docker compose -f docker-compose.dist.yml up -d

# 运行一次性命令
docker run --rm -it hfpclawer search --max-pages 1
```

## 数据持久化

| 路径 | 内容 | 推荐方式 |
|------|------|----------|
| `./config/` | config.yaml, .env | Git 追踪 |
| `./data/` | arxiv_meta.db, crawled.json | 数据卷挂载 |
| `./downloads/` | PDFs, MDS | 数据卷挂载 |

跨服务器共享存储，使用 NFS 或 S3：

```yaml
volumes:
  downloads:
    driver_opts:
      type: nfs
      o: addr=192.168.1.100,rw
      device: :/mnt/nfs/downloads
```

## 限制

- **没有 sudo？** 使用 rootless Docker（`dockerd-rootless-setuptool.sh install`）
- **GPU？** 爬取不需要，但 LLM 推理可加 `runtime: nvidia`
- **网络？** 容器的 `localhost` 是隔离的 — 使用宿主机 IP 或 Docker 网络名

## Docker vs 宿主机

| 方面 | Docker | 宿主机 (venv) |
|------|--------|---------------|
| 搭建时间 | ~2 分钟（首次构建） | ~30 秒（pip install） |
| 隔离性 | 完全 | 部分 |
| 分布式 | docker-compose | scrapy-redis + 手动 |
| 磁盘占用 | ~500 MB 镜像 | ~100 MB venv |
| 重启策略 | 内置 | systemd/supervisord |
