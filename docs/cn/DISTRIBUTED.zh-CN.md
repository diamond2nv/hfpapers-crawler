# 分布式 Scrapy 部署指南

使用 `scrapy-redis` 在两台 SSH 服务器上运行 hfpclawer 爬虫，共享队列和去重。

## 架构

```
┌─────────────┐     ┌──────────────┐
│  服务器 A    │     │  服务器 B    │
│  Scrapy      │     │  Scrapy      │
│  Spider 1..N │     │  Spider 1..N │
└──────┬───────┘     └──────┬────────┘
       │                    │
       └────────┬───────────┘
                ▼
        ┌───────────────┐
        │  Redis (队列   │
        │  + 去重过滤器) │
        │  运行在 A 上  │
        └───────────────┘
```

## 前置条件

- 两台服务器之间可通过 SSH 互访
- 均需 `pip install hfpclawer[scrapy]`（Python 3.10+）
- Redis 安装在服务器 A（或专用机器）

## 第 1 步：在服务器 A 上安装 Redis

```bash
# 没有 sudo？用 conda 或源码编译
conda install -c conda-forge redis-server

# 或通过 pip（轻量替代方案）
pip install redis

# 启动 Redis（自定义端口避免冲突）
redis-server --port 16379 --daemonize yes
```

检查: `redis-cli -p 16379 ping` → `PONG`

## 第 2 步：配置爬虫设置

编辑 `settings.py`（或通过环境变量传入）：

```python
# settings.py
SCHEDULER = "scrapy_redis.scheduler.Scheduler"
DUPEFILTER_CLASS = "scrapy_redis.dupefilter.RFPDupeFilter"
SCHEDULER_PERSIST = True  # 保持队列在重启间持久

# 指向服务器 A 的 Redis
REDIS_URL = "redis://192.168.1.100:16379"  # 替换为 A 的 IP

# 限速 — 每个爬虫独立遵守
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 4
DOWNLOAD_DELAY = 1.0
RANDOMIZE_DOWNLOAD_DELAY = True
```

## 第 3 步：在双服务器上运行

```bash
# 服务器 A（同时运行 Redis）
cd /path/to/hfpapers-crawler
hfpclawer crawl arxiv        # 启动爬虫，从共享队列拉取

# 服务器 B（从 A 通过 SSH 启动）
ssh user@server-b "cd /path/to/hfpapers-crawler && hfpclawer crawl arxiv"
```

两台爬虫共享同一个请求队列和去重集合。

## 第 4 步：监控进度

```bash
# 检查队列大小
redis-cli -p 16379 LLEN hfpclawer:requests

# 检查去重数量
redis-cli -p 16379 SCARD hfpclawer:dupefilter

# 清空队列（重置）
redis-cli -p 16379 FLUSHDB
```

## 注意事项

| 关注点 | 解决方案 |
|--------|----------|
| **重启间去重** | `SCHEDULER_PERSIST = True` 保持 Redis 状态 |
| **限速** | 每个爬虫遵守自己的 `DOWNLOAD_DELAY` + `CONCURRENT_REQUESTS` |
| **文件存储** | PDF/MD 存到各服务器本地磁盘 — 用 NFS/S3 实现共享存储 |
| **日志集中** | 每台服务器设置 `LOG_FILE` 并在文件名中加入主机名: `logs/arxiv_serverA.log` |
| **优雅停止** | `scrapy crawl arxiv -s JOBDIR=crawls/arxiv` — 支持暂停/恢复 |

## 优雅关闭

```bash
# 暂停: 直接 Ctrl+C 或 kill -TERM
# 恢复: 使用相同 JOBDIR 重启
scrapy crawl arxiv -s JOBDIR=crawls/arxiv
```

或通过 Redis：

```bash
# 排空队列，不丢失请求
redis-cli -p 16379 LTRIM hfpclawer:requests 0 -1
```

## 故障排除

### Redis 连接拒绝
- 检查防火墙: `sudo ufw status`（如有 sudo）
- 或用 SSH 隧道: `ssh -L 16379:localhost:16379 server-a`

### 跨爬虫的重复请求
- 正常 — scrapy-redis 通过共享去重过滤器确保不重复爬取
- 确保所有爬虫的 `SCHEDULER_PERSIST = True`

### 数据库冲突
- 默认每个爬虫写入自己的 SQLite
- 要共享数据库: 使用 MariaDB/PostgreSQL，或将 `db.path` 指向同一 NFS 路径
- **注意**: SQLite 不适合并发写入 — 生产环境请切换为合适的数据库

## 参考

- [scrapy-redis 文档](https://github.com/rmax/scrapy-redis)
- [Scrapy 分布式爬取最佳实践](https://docs.scrapy.org/en/latest/topics/practices.html#distributed-crawls)
