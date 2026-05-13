# settings.py
import os

BOT_NAME = "hfpapers"

SPIDER_MODULES = ["hfpapers.spiders"]
NEWSPIDER_MODULE = "hfpapers.spiders"

# ─── 反爬虫配置 ─────────────────────────────
# 从 config.yaml anti_crawl 节加载（下面有硬编码默认值）

# 遵守 robots.txt (基础礼仪)
ROBOTSTXT_OBEY = True

# 并发控制
CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 2  # 每域名限制

# 下载延迟（RandomDelayMiddleware 在此基础上做随机 ±50%）
DOWNLOAD_DELAY = 2.0
RANDOMIZE_DOWNLOAD_DELAY = False    # 我们自己的中间件做随机

# 下载超时（防止死挂）
DOWNLOAD_TIMEOUT = 30

# ─── 中间件链（执行顺序: 数字小的先执行）─────
DOWNLOADER_MIDDLEWARES = {
    # 自带中间件
    "scrapy.downloadermiddlewares.robotstxt.RobotsTxtMiddleware": 100,
    "scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware": 750,
    # 自定义中间件
    "hfpapers.middlewares.RandomUserAgentMiddleware": 200,
    "hfpapers.middlewares.RandomDelayMiddleware": 250,
    "hfpapers.middlewares.ProxyMiddleware": 350,
    "hfpapers.middlewares.CookiesPoolMiddleware": 400,
    "hfpapers.middlewares.IntelligentRetryMiddleware": 500,
    "hfpapers.middlewares.RobustDownloaderMiddleware": 510,
}

# ─── 去重 ───────────────────────────────────
# 单机模式: 默认 RFPDupeFilter
# 分布式模式: 使用 scrapy-redis (见 settings_redis.py)
DUPEFILTER_CLASS = "scrapy.dupefilters.RFPDupeFilter"
DUPEFILTER_DEBUG = True

# ─── Pipeline ───────────────────────────────
ITEM_PIPELINES = {
    "hfpapers.pipelines.StorePipeline": 100,    # 写入 SQLite + 交叉验证
    "hfpapers.pipelines.ClassifyPipeline": 200, # 分级分类
    "hfpapers.pipelines.ExportPipeline": 300,   # 导出候选列表
    "hfpapers.pipelines.DownloadPipeline": 400, # PDF 下载 + MD 转换
}

# ─── 爬取扩展 ───────────────────────────────
EXTENSIONS = {
    "scrapy.extensions.telnet.TelnetConsole": None,  # 关闭 telnet
}

# ─── 输出目录 ───────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
PDF_DIR = os.path.join(PROJECT_ROOT, "pdfs")
MD_DIR = os.path.join(PROJECT_ROOT, "mds")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")

for d in [DATA_DIR, PDF_DIR, MD_DIR, LOG_DIR]:
    os.makedirs(d, exist_ok=True)

# 已爬取记录路径
CRAWLED_JSON = os.path.expanduser("~/wiki/raw/papers/hfpapers-crawled.json")

# ─── 日志 ───────────────────────────────────
LOG_ENABLED = True
LOG_FILE = os.path.join(LOG_DIR, "spider.log")
LOG_LEVEL = "INFO"

# ─── User-Agent（默认值，中间件会覆盖）───────
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
