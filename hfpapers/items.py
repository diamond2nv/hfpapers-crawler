#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# items.py
"""Paper data model"""

import scrapy


class PaperItem(scrapy.Item):
    """Unified paper data model — all Spiders output this format"""

    # Core metadata
    arxiv_id = scrapy.Field()  # arXiv ID (e.g. "2301.11167")
    title = scrapy.Field()  # Paper title
    abstract = scrapy.Field()  # Abstract
    source = scrapy.Field()  # Source: "arxiv_api" / "openreview" / "hf_papers"
    source_url = scrapy.Field()  # Source URL
    search_category = scrapy.Field()  # Search dimension label

    # Additional info
    categories = scrapy.Field()  # arXiv categories list
    authors = scrapy.Field()  # Authors list
    venue = scrapy.Field()  # Conference/journal (e.g. "NeurIPS 2024")
    doi = scrapy.Field()  # DOI
    code_url = scrapy.Field()  # Code repository URL
    pdf_url = scrapy.Field()  # PDF download URL

    # OpenReview specific
    openreview_forum = scrapy.Field()  # Forum ID
    reviews = scrapy.Field()  # Reviews: [{"rating": "...", "comment": "..."}]

    # Processing status
    relevance_score = scrapy.Field()  # Relevance score (0-100)
    verified = scrapy.Field()  # arXiv verification status
    downloaded = scrapy.Field()  # PDF download status
