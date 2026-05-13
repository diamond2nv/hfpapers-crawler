# 分布式部署指南
#
# 前提:
# - GPU 服务器 (nautilus / ${SERVER_HOST}) — 主力
# - CPU 服务器 — 轻量爬取节点
# - 笔记本 (macOS/Ubuntu) — 本地开发 + 测试
#
# ─── 1. 安装依赖 ───────────────────────────
#
#   在所有机器上:
#   cd ~/Gitlab/Agentic4Sci/hfpapers-clawler
#   source venv/bin/activate
#   pip install scrapy-redis  # 分布式专用
#
# ─── 2. 选择 Redis 宿主 ─────────────────────
#
#   方案 A: GPU 服务器上起个轻量 Redis
#     apt install redis-server  (如有 sudo)
#     或: pip install valkey
#     valkey-server --port 6379
#
#   方案 B: 用已有 Redis (比如之前装过)
#     redis-cli -h <host> ping
#
#   方案 C: 无 Redis — 共享 JSON 模式
#     scrapy crawl multi_source
#     各机器独立跑，不做队列共享，仅共享去重文件。
#     去重文件通过类似 ~/wiki/raw/papers/hfpapers-crawled.json
#     这个可以用 NFS / scp / git 同步。
#
# ─── 3. 各机器启动 ──────────────────────────
#
#   GPU 服务器（大源搜索 + 论文下载）:
#     scrapy crawl multi_source -a source=hf_papers
#     scrapy crawl multi_source -a source=arxiv
#
#   CPU 服务器（arXiv 搜索 + 验证）:
#     scrapy crawl multi_source -a source=arxiv -s CONCURRENT_REQUESTS=8
#
#   笔记本（测试 + OpenReview 搜索）:
#     scrapy crawl multi_source -a source=openreview
#
#   分布式模式（需 Redis）:
#     scrapy crawl multi_source -s SETTINGS_MODULE=hfpapers.settings_redis
#
# ─── 4. 查看结果 ────────────────────────────
#
#   所有机器共享同样的输出:
#     data/candidates_latest.json    ← 最新候选列表
#     pdfs/                          ← PDF 文件
#     mds/                           ← MD 提取文件
#     ~/wiki/raw/papers/             ← 全局去重记录
#
# ─── 5. 反爬虫配置调整 ──────────────────────
#
#   每台机器独立配置 config.yaml:
#
#   机器 A (IP 1):
#     anti_crawl:
#       random_ua: true
#       proxy:
#         enable: true
#         providers: ["http://proxy_pool_a:8080"]
#
#   机器 B (IP 2):
#     anti_crawl:
#       random_ua: true
#       proxy:
#         providers: ["http://proxy_pool_b:8080"]
#
#   这样每台机器的出口 IP 不同，且每个请求 IP 也轮换。
#
# ─── 6. 故障恢复 ────────────────────────────
#
#   中断后重新启动，scrapy-redis 会:
#     1. 从 Redis 恢复未完成的请求队列
#     2. 跳过已去重的请求
#     3. 跳过已在数据目录中的 PDF/MD 文件
#
#   无需额外处理。
