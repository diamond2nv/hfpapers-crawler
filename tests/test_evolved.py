"""测试 evolved 模块 — 去重 + 分类 + 爬虫引擎"""
from hfpapers.search_queue import _title_similarity
from hfpapers.evolved import (
    PaperInfo, DedupEngine, RelevanceDetector, HFPapersCrawler,
    PaperDownloader,
)


class TestPaperInfo:
    def test_default_values(self):
        p = PaperInfo()
        assert p.arxiv_id == ""
        assert p.relevance == 0
        assert p.categories == []
        assert p.has_code == "unknown"

    def test_with_values(self):
        p = PaperInfo(
            arxiv_id="2001.08361",
            title="FNO test",
            relevance=80,
            categories=["FNO"],
        )
        assert p.arxiv_id == "2001.08361"
        assert p.relevance == 80


class TestDedupEngine:
    def test_init(self, test_env):
        engine = DedupEngine()
        assert hasattr(engine, "count")
        assert hasattr(engine, "is_duplicate")
        assert hasattr(engine, "add")

    def test_is_duplicate_nonexistent(self, test_env):
        engine = DedupEngine()
        p = PaperInfo(
            arxiv_id="9999.99999",
            title="nonexistent paper",
        )
        assert engine.is_duplicate(p) is None


class TestRelevanceDetector:
    def test_classify_high(self, test_env):
        detector = RelevanceDetector()
        p = PaperInfo(
            title="Fourier Neural Operator for Parametric PDEs",
            abstract="Using Fourier transforms to solve PDEs with neural operators",
        )
        score = detector.classify(p)
        assert score >= 30

    def test_classify_low(self, test_env):
        detector = RelevanceDetector()
        p = PaperInfo(
            title="Quantum Entanglement in Spin Systems",
            abstract="A theoretical study of quantum correlations",
        )
        score = detector.classify(p)
        assert score < 30

    def test_exclude(self, test_env):
        detector = RelevanceDetector()
        p = PaperInfo(
            title="Using Reinforcement Learning for Game Playing",
            abstract="Deep Q-learning for Atari games",
        )
        score = detector.classify(p)
        assert score == 0

    def test_threshold_pass(self, test_env):
        detector = RelevanceDetector()
        assert detector.threshold_pass == 30


class TestHFPapersCrawler:
    def test_title_similarity(self):
        sim = _title_similarity(
            "Fourier Neural Operator for PDEs",
            "Fourier Neural Operator for Partial Differential Equations",
        )
        assert 0.3 < sim <= 1.0

    def test_title_similarity_unrelated(self):
        sim = _title_similarity(
            "Quantum Physics",
            "Weather Forecasting",
        )
        assert sim < 0.5

    # crawl 需要在 HF CLI 可用时集成测试，这里跳过

class TestPaperDownloader:
    def test_init(self, test_env):
        dedup = DedupEngine()
        downloader = PaperDownloader(dedup=dedup)
        assert downloader.hw is not None
