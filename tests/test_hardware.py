#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test hardware module — probe detection + hardware degradation"""
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
        # Returns False without CUDA or sentence-transformers
        if not hw.has_cuda:
            assert hw.use_bert is False
        if not hw.has_sentence_transformers:
            assert hw.use_bert is False

    def test_use_pdf_converter(self):
        hw = HardwareProbe()
        from importlib.util import find_spec
        expected = find_spec("pymupdf4llm") is not None
        assert hw.use_pdf_converter == expected
