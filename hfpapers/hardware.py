#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ─── Hardware Probe ──────────────────────────────
# hfpapers/hardware.py

import logging

logger = logging.getLogger("hfpapers.hw")


class HardwareProbe:
    """Hardware capability probe — adaptive degradation"""

    has_torch: bool = False
    has_cuda: bool = False
    has_sentence_transformers: bool = False
    has_pymupdf4llm: bool = False
    gpu_name: str = ""
    gpu_count: int = 0
    is_cpu_server: bool = True
    total_ram_gb: float = 0.0

    def __init__(self):
        self._probe()

    def _probe(self):
        # RAM — gracefully degrade if psutil is broken (e.g. version mismatch)
        try:
            import psutil
            self.total_ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)
        except Exception as e:
            logger.warning("Failed to probe RAM via psutil: %s", e)
            self.total_ram_gb = 0.0

        # PyTorch + CUDA
        try:
            import torch

            self.has_torch = True
            self.has_cuda = torch.cuda.is_available()
            if self.has_cuda:
                self.gpu_count = torch.cuda.device_count()
                self.gpu_name = torch.cuda.get_device_name(0)
                self.is_cpu_server = False
                logger.info(f"GPU: {self.gpu_name} x{self.gpu_count}")
            else:
                self.is_cpu_server = True
        except ImportError:
            self.has_torch = False
            self.is_cpu_server = True

        # sentence-transformers
        try:
            import sentence_transformers  # noqa

            self.has_sentence_transformers = True
        except ImportError:
            self.has_sentence_transformers = False

        # pymupdf4llm
        try:
            import pymupdf4llm  # noqa

            self.has_pymupdf4llm = True
        except ImportError:
            self.has_pymupdf4llm = False

        logger.info(
            f"RAM: {self.total_ram_gb}GB | {'CPU Server' if self.is_cpu_server else 'GPU Server'}"
        )

    @property
    def use_bert(self) -> bool:
        """BERT only enabled when GPU is available"""
        return self.has_cuda and self.has_sentence_transformers

    @property
    def use_pdf_converter(self) -> bool:
        """pymupdf4llm available"""
        return self.has_pymupdf4llm

    def summary(self) -> str:
        parts = []
        if self.is_cpu_server:
            parts.append("CPU Server")
        else:
            parts.append(f"GPU: {self.gpu_name}")
        parts.append(f"RAM: {self.total_ram_gb}GB")
        if self.has_cuda:
            parts.append("CUDA✓")
        if self.has_sentence_transformers:
            parts.append("BERT✓")
        return " | ".join(parts)
