#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# spiders/hfspider.py
"""
[LEGACY — deprecated, no longer used]
HF Papers multi-dimension crawler — migrated to SearchDispatcher (hfpapers/search_queue.py)
Retained for reference. New development should use evolved.py / SearchDispatcher.
"""

import re

import scrapy

from hfpapers.items import PaperItem

# Search dimension config: (url, category, min_relevance)
SEARCH_DIMS = [
    # Main dimension: PDE + neural operator + physics-informed
    ("https://huggingface.co/papers/trending?q=PDE+neural+operator+physics-informed", "neural-operator", 3),
    # Physical constraint residual
    ("https://huggingface.co/papers?q=physical+constraint+residual+loss+PDE", "pinn", 3),
    # AI4Science surrogate models
    ("https://huggingface.co/papers?q=AI+4+Science+neural+surrogate", "foundation-model", 3),
    # Neural operator + physics-informed
    ("https://huggingface.co/papers?q=neural+operator+physics+informed", "neural-operator", 2),
    # PDE solution operators
    ("https://huggingface.co/papers?q=PDE+solution+operators", "foundation-model", 2),
]

# arXiv ID regex (extracts from text)
ARXIV_RE = re.compile(r"(?:arxiv\s*[:.]?\s*|/abs/|/pdf/)?(\d{4}\.\d{4,5})(?:v\d+)?", re.I)

# Code repository URL regex
CODE_RE = re.compile(r"(?:github\.com|gitlab\.com|huggingface\.co)/([\w\-]+/[\w\-]+)")


class HFPapersSpider(scrapy.Spider):
    name = "hfpapers"
    allowed_domains = ["huggingface.co", "arxiv.org"]
    custom_settings = {
        "DOWNLOAD_DELAY": 2.0,
        "CONCURRENT_REQUESTS": 4,
        "COOKIES_ENABLED": False,
    }

    def start_requests(self):
        """Initiate multi-dimensional requests in parallel"""
        for url, category, min_rel in SEARCH_DIMS:
            yield scrapy.Request(
                url=url,
                callback=self.parse_search_page,
                meta={"category": category, "min_relevance": min_rel},
            )

    def parse_search_page(self, response):
        """Parse HF Papers search page — extract paper blocks"""
        category = response.meta["category"]
        min_rel = response.meta["min_relevance"]

        # Try multiple CSS selectors to extract paper cards
        papers = response.css("article, .paper-card, [class*='paper'], li")
        if not papers:
            papers = response.css("div > a[href*='/papers/']")

        seen_ids = set()
        for paper in papers:
            text = paper.css("::text").getall()
            full_text = " ".join(text)

            # Extract arXiv ID
            arxiv_matches = ARXIV_RE.findall(full_text)
            if not arxiv_matches:
                # May also be in href
                hrefs = paper.css("a[href]::attr(href)").getall()
                for h in hrefs:
                    arxiv_matches = ARXIV_RE.findall(h)
                    if arxiv_matches:
                        break
            if not arxiv_matches:
                continue

            arxiv_id = arxiv_matches[0]
            if arxiv_id in seen_ids:
                continue
            seen_ids.add(arxiv_id)

            # Extract title (usually first <a> or <h3> text)
            title = paper.css("h3::text, h2::text, a[href*='/papers/']::text").get()
            if not title:
                # Get first meaningful line from full text
                lines = [t.strip() for t in text if t.strip() and len(t.strip()) > 10]
                title = lines[0] if lines else ""

            # Extract description
            desc_lines = [t.strip() for t in text if t.strip() and t.strip() != title and len(t.strip()) > 20]
            description = desc_lines[0][:200] if desc_lines else ""

            # GitHub code check
            code_match = CODE_RE.search(full_text)
            code_url = f"https://github.com/{code_match.group(1)}" if code_match else ""

            # Relevance scoring
            relevance = self._score_relevance(full_text, category)

            if relevance < min_rel:
                continue

            item = PaperItem(
                arxiv_id=arxiv_id,
                title=title.strip()[:150],
                description=description.strip()[:300],
                source_dim=category,
                source_url=response.url,
                has_code="yes" if code_url else "unknown",
                code_url=code_url,
                relevance=relevance,
                category=category,
            )
            yield item

        # Recursive pagination
        next_page = response.css("a:contains('Next'), a:contains('next'), a[rel='next']::attr(href)").get()
        if next_page and "?" in next_page:
            yield scrapy.Request(
                url=response.urljoin(next_page),
                callback=self.parse_search_page,
                meta={"category": category, "min_relevance": min_rel},
            )

    def _score_relevance(self, text, category):
        """Score 1-5 based on keywords"""
        score = 1
        keywords_high = [
            "neural operator", "fourier neural operator", "deeponet", "pino",
            "physics-informed", "pinn", "pde", "partial differential", "flow matching",
            "foundation model", "surrogate", "operator learning",
            "conservation law", "physical constraint", "residual loss",
        ]
        keywords_med = [
            "simulation", "cfd", "fluid", "navier-stokes", "burgers",
            "scientific machine learning", "mesh", "turbulence",
        ]
        text_lower = text.lower()
        for kw in keywords_high:
            if kw in text_lower:
                score += 1
        for kw in keywords_med:
            if kw in text_lower:
                score += 0.5
        return min(int(score), 5)
