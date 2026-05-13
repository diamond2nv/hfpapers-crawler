# items.py
"""论文数据模型"""

import scrapy


class PaperItem(scrapy.Item):
    """统一论文数据模型 — 所有 Spider 输出此格式"""
    
    # 核心元数据
    arxiv_id = scrapy.Field()       # arXiv ID (如 "2301.11167")
    title = scrapy.Field()          # 论文标题
    abstract = scrapy.Field()       # 摘要
    source = scrapy.Field()         # 来源: "arxiv_api" / "openreview" / "hf_papers"
    source_url = scrapy.Field()     # 来源 URL
    search_category = scrapy.Field() # 搜索维度标签

    # 额外信息
    categories = scrapy.Field()     # arXiv categories 列表
    authors = scrapy.Field()        # 作者列表
    venue = scrapy.Field()          # 会议/期刊 (如 "NeurIPS 2024")
    doi = scrapy.Field()            # DOI
    code_url = scrapy.Field()       # 代码仓库 URL
    pdf_url = scrapy.Field()        # PDF 下载 URL

    # OpenReview 专属
    openreview_forum = scrapy.Field()  # forum ID
    reviews = scrapy.Field()           # 审稿: [{"rating": "...", "comment": "..."}]

    # 处理状态
    relevance_score = scrapy.Field()   # 相关度 (0-100)
    verified = scrapy.Field()          # arXiv 验证状态
    downloaded = scrapy.Field()        # PDF 下载状态
