# middlewares.py
"""
反爬中间件链 — 多层防护，每层可独立启用/禁用

配置 (config.yaml):
  anti_crawl:
    random_ua: true
    auto_throttle: true           # 自适应延迟 (AutoThrottle)
    proxy:
      enable: false               # 代理轮换（默认关，需要代理池）
      providers: []               # e.g. ["http://user:pass@proxy1:8080"]
    cookies:
      enable: false               # Cookie 池（默认关）
    max_retries: 3                # 最大重试次数
    retry_delay_base: 30          # 指数退避基数（秒）
    retry_http_codes: [429, 503, 403, 408, 500, 502, 520]
"""

import random
import time
import logging
from urllib.parse import urlparse

from scrapy import signals
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.response import response_status_message

from hfpapers.config import get as cfg_get

logger = logging.getLogger(__name__)

# ─── 完整的 UA 池（涵盖 Chrome/Firefox/Edge 多版本）───
USER_AGENTS = [
    # Chrome 120+
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Firefox 115+ / 122+
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0",
    # Edge 120+
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    # Safari 17
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]


class RandomUserAgentMiddleware:
    """随机 User-Agent (每请求随机换)"""

    def process_request(self, request, spider):
        if cfg_get("anti_crawl.random_ua", True):
            request.headers["User-Agent"] = random.choice(USER_AGENTS)

    def process_response(self, request, response, spider):
        # 503等也可能重置UA
        if response.status in (503, 429) and cfg_get("anti_crawl.random_ua", True):
            request.headers["User-Agent"] = random.choice(USER_AGENTS)
        return response


class RandomDelayMiddleware:
    """随机延迟 — 在 DOWNLOAD_DELAY 基础上 ±50% 随机抖动
    
    防止固定间隔模式被反爬检测到
    """

    def process_request(self, request, spider):
        base = cfg_get("anti_crawl.random_delay.base", spider.settings.get("DOWNLOAD_DELAY", 2.0))
        jitter = cfg_get("anti_crawl.random_delay.jitter", 0.5)
        delay = base * (1.0 + random.uniform(-jitter, jitter))
        delay = max(0.1, delay)
        time.sleep(delay)


class ProxyMiddleware:
    """代理轮换中间件

    使用方式:
      config.yaml:
        anti_crawl:
          proxy:
            enable: true
            providers:
              - "http://user:pass@proxy1:port"
              - "http://user:pass@proxy2:port"
    
    当 proxy.enable=true 且 providers 不为空时启用。
    默认禁用，因为需要代理服务。
    """

    def __init__(self):
        proxy_cfg = cfg_get("anti_crawl.proxy", {})
        self.enabled = proxy_cfg.get("enable", False)
        self.providers = proxy_cfg.get("providers", [])
        self._current = 0

    @classmethod
    def from_clawler(cls, clawler):
        return cls()

    def process_request(self, request, spider):
        if not self.enabled or not self.providers:
            return None

        # 简单轮换 + 随机偏移避免模式
        idx = (self._current + random.randint(0, 1)) % len(self.providers)
        self._current = (self._current + 1) % len(self.providers)
        request.meta["proxy"] = self.providers[idx]

        # 随机 X-Forwarded-For 模仿不同客户端 IP
        fake_ip = f"10.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
        request.headers["X-Forwarded-For"] = fake_ip


class CookiesPoolMiddleware:
    """Cookie 池中间件

    为每个目标域名维护一个物理机 Cookie（不跨域泄露）
    从 Cookie 文件中随机读取一组物理机 Cookie
    """

    def __init__(self):
        cookie_cfg = cfg_get("anti_crawl.cookies", {})
        self.enabled = cookie_cfg.get("enable", False)
        self._cookies: dict[str, list[dict]] = {}  # domain → [cookies, ...]

    def process_request(self, request, spider):
        if not self.enabled:
            return

        domain = urlparse(request.url).netloc
        cookies = self._cookies.get(domain, [])
        if cookies:
            cookie = random.choice(cookies)
            # scrapy 的 cookies 中间件会自动处理
            for key, val in cookie.items():
                request.cookies[key] = val


class IntelligentRetryMiddleware(RetryMiddleware):
    """智能重试 — 带指数退避 + 不同状态码不同等待时间

    对 429 (Rate Limited) 增加等待时间；
    对 5xx 快速重试；
    对 403 (Forbidden) 换 UA 后重试。
    """

    def __init__(self, settings):
        super().__init__(settings)
        anti = cfg_get("anti_crawl", {})
        self.retry_http_codes = set(anti.get("retry_http_codes", [429, 503, 403, 408, 520]))
        self.delay_base = anti.get("retry_delay_base", 30)

    @classmethod
    def from_clawler(cls, clawler):
        # Scrapy 的 RetryMiddleware.from_clawler 需要 clawler 参数
        settings = clawler.settings
        obj = cls(settings)
        obj.clawler = clawler  # 保存 clawler 引用
        return obj

    def process_response(self, request, response, spider):
        if response.status in self.retry_http_codes:
            reason = response_status_message(response.status)

            if response.status == 429:
                # 尝试读取 Retry-After 头
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = int(retry_after)
                    except ValueError:
                        delay = self.delay_base
                else:
                    # 指数退避：基于已重试次数
                    retries = request.meta.get("retry_times", 0) + 1
                    delay = min(self.delay_base * (2 ** (retries - 1)), 600)
                    delay += random.uniform(0, 5)  # 加随机量
            elif response.status == 403:
                # 403 换 UA 重试
                request.headers["User-Agent"] = random.choice(USER_AGENTS)
                delay = 5 + random.uniform(0, 5)
            else:
                retries = request.meta.get("retry_times", 0) + 1
                delay = min(self.delay_base * (2 ** (retries - 1)), 120)
                delay += random.uniform(0, 2)

            spider.logger.warning(
                f"[ANTI-CRAWL] {response.status} on {request.url}, "
                f"waiting {delay:.0f}s (retry #{request.meta.get('retry_times', 0) + 1})"
            )

            # 手动等待
            time.sleep(delay)
            return self._retry(request, reason, spider) or response

        return super().process_response(request, response, spider)


class RobustDownloaderMiddleware:
    """稳健下载器 — 连接超时处理 + 下游反爬检测"""

    def process_exception(self, request, exception, spider):
        from scrapy.exceptions import IgnoreRequest
        err_name = type(exception).__name__
        spider.logger.warning(f"[ANTI-CRAWL] {err_name} on {request.url}")

        # 对超时类异常自动重试
        timeout_errors = ("TimeoutError", "ConnectTimeout", "ReadTimeout")
        if any(e in err_name for e in timeout_errors):
            retries = request.meta.get("retry_times", 0) + 1
            if retries <= cfg_get("anti_crawl.max_retries", 3):
                request.meta["retry_times"] = retries
                delay = min(30 * (2 ** (retries - 1)), 300)
                spider.logger.info(f"  → 重试 (retry #{retries}) after {delay}s")
                time.sleep(delay)
                return request
            else:
                raise IgnoreRequest(f"Max retries exceeded: {request.url}")

        return None
