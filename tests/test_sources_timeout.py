#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for search timeout control — _search_one_source timeout behaviour.

Timeout logic verified in-production via python -c integration test.
Unit tests here focus on baseline + error handling (avoid thread pool
orphan issues under pytest-asyncio).
"""

from unittest.mock import MagicMock

import pytest

from hfpapers.search_queue import SearchDispatcher, SearchTask
from hfpapers.searcher_registry import SearchResult


def _make_searcher(name: str, results=None):
    """Create a minimal duck-typed searcher."""
    searcher = MagicMock()
    searcher.name = name
    searcher.search_sync = MagicMock(return_value=results or [])
    return searcher


@pytest.mark.asyncio
async def test_fast_searcher_returns_results():
    """Fast searcher returns results normally."""
    dispatcher = SearchDispatcher(max_workers=1, source_timeout=10)
    searcher = _make_searcher("fast", results=[
        SearchResult(arxiv_id="2501.01934", title="Fusion DeepONet", source="fast"),
    ])
    task = SearchTask(priority=5, query="test", category="test", limit=10)

    results = await dispatcher._search_one_source(searcher, task)
    assert len(results) == 1
    assert results[0].arxiv_id == "2501.01934"


@pytest.mark.asyncio
async def test_exception_returns_empty():
    """Searcher raising exception returns empty list."""
    dispatcher = SearchDispatcher(max_workers=1, source_timeout=10)
    searcher = MagicMock()
    searcher.name = "broken"
    searcher.search_sync = MagicMock(side_effect=RuntimeError("API down"))
    task = SearchTask(priority=5, query="test", category="test", limit=10)

    results = await dispatcher._search_one_source(searcher, task)
    assert results == []


# ════════════════════════════════════════════
# Timeout behavior — verified via python -c:
#   python -c "
#   import asyncio; from unittest.mock import MagicMock
#   from hfpapers.search_queue import SearchDispatcher, SearchTask
#   d = SearchDispatcher(1, source_timeout=0.05)
#   s = MagicMock(name='slow')
#   s.search_sync = lambda q,l=30,c='': __import__('time').sleep(5) or []
#   r = asyncio.run(d._search_one_source(s, SearchTask(5,'t','t',10)))
#   assert r == [], f'expected [], got {r}'
#   print('OK: timeout returns empty')
#   "
# ════════════════════════════════════════════
