#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_paper — Atomic paper import pipeline.

Import a paper by arXiv ID / DOI / URL:
    resolve → dedup → PDF download (3-level fallback)
    → pymupdf4llm → PaperStore write
"""
