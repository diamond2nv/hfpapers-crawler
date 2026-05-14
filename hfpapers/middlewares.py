#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# middlewares.py
"""
Anti-crawl middleware chain — multi-layer protection, each layer independently enable/disable

Configuration (config.yaml):
  anti_crawl:
    random_ua: true
    auto_throttle: true           # Adaptive delay (AutoThrottle)
    proxy:
      enable: false               # Proxy rotation (default off, requires proxy pool)
      providers: []               # e.g. ["http://user:pass@proxy1:8080"]
    cookies:
      enable: false               # Cookie pool (default off)
    max_retries: 3                # Maximum retries
    retry_delay_base: 30          # Exponential backoff base (seconds)
    retry_http_codes: [429, 503, 403, 408, 500, 502, 520]
"""

import logging
import random
import time
from urllib.parse import urlparse

from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.response import response_status_message

from hfpapers.config import get as cfg_get

logger = logging.getLogger(__name__)

# ─── Complete UA pool (covering Chrome/Firefox/Edge multiple versions) ───
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
    """Random User-Agent (randomly swapped per request)"""

    def process_request(self, request, spider):
        if cfg_get("anti_crawl.random_ua", True):
            request.headers["User-Agent"] = random.choice(USER_AGENTS)

    def process_response(self, request, response, spider):
        # 503 etc. may also reset UA
        if response.status in (503, 429) and cfg_get("anti_crawl.random_ua", True):
            request.headers["User-Agent"] = random.choice(USER_AGENTS)
        return response


class RandomDelayMiddleware:
    """Random delay — ±50% jitter on top of DOWNLOAD_DELAY

    Prevents fixed-interval pattern detection by anti-crawl mechanisms
    """

    def process_request(self, request, spider):
        base = cfg_get("anti_crawl.random_delay.base", spider.settings.get("DOWNLOAD_DELAY", 2.0))
        jitter = cfg_get("anti_crawl.random_delay.jitter", 0.5)
        delay = base * (1.0 + random.uniform(-jitter, jitter))
        delay = max(0.1, delay)
        time.sleep(delay)


class ProxyMiddleware:
    """Proxy rotation middleware

    Usage:
      config.yaml:
        anti_crawl:
          proxy:
            enable: true
            providers:
              - "http://user:pass@proxy1:port"
              - "http://user:pass@proxy2:port"

    Enabled when proxy.enable=true and providers is non-empty.
    Disabled by default as it requires a proxy service.
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

        # Simple round-robin + random offset to avoid patterns
        idx = (self._current + random.randint(0, 1)) % len(self.providers)
        self._current = (self._current + 1) % len(self.providers)
        request.meta["proxy"] = self.providers[idx]

        # Random X-Forwarded-For to mimic different client IPs
        fake_ip = f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
        request.headers["X-Forwarded-For"] = fake_ip


class CookiesPoolMiddleware:
    """Cookie pool middleware

    Maintains real browser cookies per target domain (no cross-domain leakage)
    Randomly reads a set of real browser cookies from cookie file
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
            # Scrapy's cookies middleware handles this automatically
            for key, val in cookie.items():
                request.cookies[key] = val


class IntelligentRetryMiddleware(RetryMiddleware):
    """Intelligent retry — with exponential backoff + status-code-specific wait times

    Increases wait time for 429 (Rate Limited);
    Fast retry for 5xx;
    Switches UA before retrying 403 (Forbidden).
    """

    def __init__(self, settings):
        super().__init__(settings)
        anti = cfg_get("anti_crawl", {})
        self.retry_http_codes = set(anti.get("retry_http_codes", [429, 503, 403, 408, 520]))
        self.delay_base = anti.get("retry_delay_base", 30)

    @classmethod
    def from_clawler(cls, clawler):
        # Scrapy's RetryMiddleware.from_clawler requires clawler parameter
        settings = clawler.settings
        obj = cls(settings)
        obj.clawler = clawler  # Store clawler reference
        return obj

    def process_response(self, request, response, spider):
        if response.status in self.retry_http_codes:
            reason = response_status_message(response.status)

            if response.status == 429:
                # Try to read Retry-After header
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = int(retry_after)
                    except ValueError:
                        delay = self.delay_base
                else:
                    # Exponential backoff based on retry count
                    retries = request.meta.get("retry_times", 0) + 1
                    delay = min(self.delay_base * (2 ** (retries - 1)), 600)
                    delay += random.uniform(0, 5)  # Add random jitter
            elif response.status == 403:
                # 403: switch UA and retry
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

            # Manual wait
            time.sleep(delay)
            return self._retry(request, reason, spider) or response

        return super().process_response(request, response, spider)


class RobustDownloaderMiddleware:
    """Robust downloader — connection timeout handling + downstream anti-crawl detection"""

    def process_exception(self, request, exception, spider):
        from scrapy.exceptions import IgnoreRequest

        err_name = type(exception).__name__
        spider.logger.warning(f"[ANTI-CRAWL] {err_name} on {request.url}")

        # Auto-retry on timeout-type exceptions
        timeout_errors = ("TimeoutError", "ConnectTimeout", "ReadTimeout")
        if any(e in err_name for e in timeout_errors):
            retries = request.meta.get("retry_times", 0) + 1
            if retries <= cfg_get("anti_crawl.max_retries", 3):
                request.meta["retry_times"] = retries
                delay = min(30 * (2 ** (retries - 1)), 300)
                spider.logger.info(f"  → Retry (retry #{retries}) after {delay}s")
                time.sleep(delay)
                return request
            else:
                raise IgnoreRequest(f"Max retries exceeded: {request.url}")

        return None
