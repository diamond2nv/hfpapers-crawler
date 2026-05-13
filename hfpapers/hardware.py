# ─── 硬件探针 ──────────────────────────────
# hfpapers/hardware.py

import logging
from typing import Optional

logger = logging.getLogger("hfpapers.hw")


class HardwareProbe:
    """硬件能力探测——自适应降级"""
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
        import psutil
        self.total_ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)

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

        logger.info(f"RAM: {self.total_ram_gb}GB | {'CPU Server' if self.is_cpu_server else 'GPU Server'}")

    @property
    def use_bert(self) -> bool:
        """有 GPU 才启用 BERT"""
        return self.has_cuda and self.has_sentence_transformers

    @property
    def use_pdf_converter(self) -> bool:
        """pymupdf4llm 可用"""
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
