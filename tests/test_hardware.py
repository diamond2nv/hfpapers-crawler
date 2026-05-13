"""测试 hardware 模块 — 探针检测 + 硬件降级"""
from hfpapers.hardware import HardwareProbe


class TestHardwareProbe:
    def test_probe_has_basic_attrs(self):
        hw = HardwareProbe()
        assert hasattr(hw, "has_torch")
        assert hasattr(hw, "has_cuda")
        assert hasattr(hw, "is_cpu_server")
        assert hw.total_ram_gb > 0

    def test_probe_summary(self):
        hw = HardwareProbe()
        summary = hw.summary()
        assert "RAM:" in summary

    def test_use_bert_property(self):
        hw = HardwareProbe()
        # 没有 CUDA 或没有 sentence-transformers 时返回 False
        if not hw.has_cuda:
            assert hw.use_bert is False
        if not hw.has_sentence_transformers:
            assert hw.use_bert is False

    def test_use_pdf_converter(self):
        hw = HardwareProbe()
        from importlib.util import find_spec
        expected = find_spec("pymupdf4llm") is not None
        assert hw.use_pdf_converter == expected
