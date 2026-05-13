# pipelines.py
"""
Pipeline 链 — 每个 stage 处理一个 PaperItem

Flow:
  0. Items 进入
  1. StorePipeline — 写入 paper_store (SQLite + 雪花ID + Crossref交叉验证)
  2. ClassifyPipeline — 相关度分类（关键词/NLP）
  3. ExportPipeline — 导出候选列表 + 更新全局去重
  4. DownloadPipeline — PDF 下载 + MD 转换
"""

import logging
import os
from datetime import datetime

from hfpapers.config import get as cfg_get, load_config
from hfpapers.items import PaperItem
from hfpapers.paper_store import PaperStore, get_store, get_crossref, ensure_paper

logger = logging.getLogger(__name__)


class StorePipeline:
    """Paper Store Pipeline — 写入 SQLite 统一存储层

    功能:
      1. 用 ensure_paper() 检查去重（arXiv ID 防重）
      2. 自动触发 Crossref 交叉验证（title → DOI）
      3. 多标识符自动 verified
      4. 返回 sf_id 供后续 Pipeline 使用
    """

    def __init__(self):
        self.skipped = 0
        self.passed = 0

    def process_item(self, item: PaperItem, spider):
        arxiv_id = item.get("arxiv_id", "")
        if not arxiv_id:
            self.skipped += 1
            return None

        title = item.get("title", "")
        abstract = item.get("abstract", "")
        code_url = item.get("code_url", "")
        venue = item.get("venue", "")

        # 写入 paper_store（去重 + 交叉验证）
        sf_id, is_new = ensure_paper(
            arxiv_id=arxiv_id,
            title=title,
            abstract=abstract,
            source=item.get("source", "scrapy"),
            relevance=item.get("relevance_score", 0),
            venue=venue,
            code_url=code_url,
        )

        if not is_new:
            spider.logger.info(f"[STORE] 跳过 (已存在): {arxiv_id} {title[:40]}")
            self.skipped += 1
            return None

        # 回写 sf_id 供后续 pipeline 使用
        item["sf_id"] = sf_id
        item["verified"] = True  # paper_store 已做验证
        self.passed += 1
        return item

    def open_spider(self, spider):
        store = get_store()
        stats = store.stats()
        spider.logger.info(f"[STORE] 论文存储: {stats['papers_total']} 篇, {stats['papers_verified']} 已验证")

    def close_spider(self, spider):
        logger.info(f"[STORE] 本次: {self.passed} 新入库, {self.skipped} 跳过")


class ClassifyPipeline:
    """分类 Pipeline — 关键词/短语 分级评分"""

    def __init__(self):
        cfg = load_config()
        kw = cfg.get("keywords", {})
        self.include_high = kw.get("include_high", [])
        self.include_med = kw.get("include_medium", [])
        self.include_low = kw.get("include_low", [])
        self.exclude = kw.get("exclude", [])
        self.phrase_high = cfg.get("classification", {}).get("phrase_high", [])
        self.threshold_pass = cfg.get("classification", {}).get("threshold_pass", 30)

    def process_item(self, item: PaperItem, spider):
        text = f"{item.get('title', '')}\n{item.get('abstract', '')}".lower()

        # 黑名单检查
        for kw in self.exclude:
            if kw in text:
                spider.logger.info(f"[CLASSIFY] {item['arxiv_id']} 黑名单命中: {kw}")
                return None

        score = self._keyword_score(text)
        score = max(score, self._phrase_score(text))
        score = min(score, 100)
        item["relevance_score"] = score

        if score >= self.threshold_pass:
            spider.logger.info(f"[CLASSIFY] {item['arxiv_id']} rel={score}")
            return item
        else:
            spider.logger.info(f"[CLASSIFY] {item['arxiv_id']} rel={score} 低于阈值 {self.threshold_pass}")
            return None

    def _keyword_score(self, text: str) -> int:
        score = 0
        for kw in self.include_high:
            if kw in text:
                score += 20
        for kw in self.include_med:
            if kw in text:
                score += 10
        for kw in self.include_low:
            if kw in text:
                score += 5
        return min(score, 100)

    def _phrase_score(self, text: str) -> int:
        if not self.phrase_high:
            return 0
        score = 0
        for ph in self.phrase_high:
            if ph.lower() in text:
                score += 15
        return min(score, 80)


class ExportPipeline:
    """导出 Pipeline — 保存候选列表 + 更新 paper_store

    此 pipeline 同时维护：
      1. paper_store (SQLite) — 主存储
      2. candidates_latest.json — 兼容旧的 JSON 导出
    """

    def __init__(self):
        self.candidates: list[dict] = []
        self.today = datetime.now().strftime("%Y-%m-%d")

    def process_item(self, item: PaperItem, spider):
        sf_id = item.get("sf_id", 0)
        arxiv_id = item.get("arxiv_id", "")
        title = item.get("title", "")
        abstract = item.get("abstract", "")
        relevance = item.get("relevance_score", 0)
        code_url = item.get("code_url", "")
        venue = item.get("venue", "")

        # 更新 paper_store 的 relevance 和 code_url
        if sf_id:
            store = get_store()
            store.update_paper(sf_id, relevance=relevance, code_url=code_url)

        # JSON 导出缓存
        self.candidates.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": abstract[:300],
            "relevance": relevance,
            "category": item.get("search_category", ""),
            "source": item.get("source", ""),
            "source_url": item.get("source_url", ""),
            "code_url": code_url,
            "venue": venue,
            "verified": item.get("verified", False),
        })
        return item

    def close_spider(self, spider):
        if not self.candidates:
            logger.info("[EXPORT] 无候选论文")
            return

        # 按 relevance 排序
        self.candidates.sort(key=lambda x: x["relevance"], reverse=True)

        # 写入 JSON 文件（向后兼容）
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                cfg_get("paths.data_dir", "data"))
        os.makedirs(data_dir, exist_ok=True)

        filepath = os.path.join(data_dir, f"candidates_{self.today}.json")
        with open(filepath, "w") as f:
            import json
            json.dump(self.candidates, f, indent=2, ensure_ascii=False)

        latest = os.path.join(data_dir, "candidates_latest.json")
        with open(latest, "w") as f:
            import json
            json.dump(self.candidates, f, indent=2, ensure_ascii=False)

        logger.info(f"[EXPORT] {len(self.candidates)} 篇 → {filepath} + paper_store")


class DownloadPipeline:
    """下载 Pipeline — PDF 下载 + MD 转换"""

    def __init__(self):
        import requests
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

        base = os.path.dirname(os.path.dirname(__file__))
        self.pdf_dir = os.path.join(base, cfg_get("paths.pdf_dir", "pdfs"))
        self.md_dir = os.path.join(base, cfg_get("paths.md_dir", "mds"))
        os.makedirs(self.pdf_dir, exist_ok=True)
        os.makedirs(self.md_dir, exist_ok=True)

    def process_item(self, item: PaperItem, spider):
        arxiv_id = item.get("arxiv_id", "")
        if not arxiv_id:
            return item

        pdf_path = os.path.join(self.pdf_dir, f"{arxiv_id}.pdf")

        if not os.path.exists(pdf_path):
            try:
                resp = self.session.get(f"https://arxiv.org/pdf/{arxiv_id}", timeout=60)
                if resp.status_code == 200 and len(resp.content) > 5000:
                    with open(pdf_path, "wb") as f:
                        f.write(resp.content)
                    spider.logger.info(f"[DOWNLOAD] {arxiv_id} PDF ({len(resp.content)//1024}KB)")
                    item["downloaded"] = True
            except Exception as e:
                spider.logger.warning(f"[DOWNLOAD] {arxiv_id} PDF失败: {e}")
                item["downloaded"] = False
        else:
            item["downloaded"] = True

        # 转换 MD
        md_path = os.path.join(self.md_dir, f"{arxiv_id}.md")
        if os.path.exists(pdf_path) and not os.path.exists(md_path):
            try:
                import pymupdf4llm
                md_text = pymupdf4llm.to_markdown(pdf_path)
                title = item.get("title", arxiv_id)
                with open(md_path, "w") as f:
                    f.write(f"# {title} ({arxiv_id})\n\n> arXiv PDF\n\n{md_text}")
                spider.logger.info(f"[CONVERT] {arxiv_id} MD ({len(md_text)} chars)")
            except Exception as e:
                spider.logger.warning(f"[CONVERT] {arxiv_id} MD失败: {e}")

        return item
