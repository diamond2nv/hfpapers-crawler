#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for hub-guided layered citation expansion."""

import json
import os

import networkx as nx
import pytest

from hfpapers.graph import NodeType
from hfpapers.graph.citation_expander import HubGuidedExpander, _hub_scores


def _make_graph():
    """Small citation graph: A cited by B,C; B cited by D,E; C cited by F."""
    G = nx.Graph()
    papers = {
        "paper:a": {"type": NodeType.PAPER, "arxiv_id": "2001.00001", "sources": "s2_hub", "label": "A"},
        "paper:b": {"type": NodeType.PAPER, "arxiv_id": "2001.00002", "sources": "s2_hub", "label": "B"},
        "paper:c": {"type": NodeType.PAPER, "arxiv_id": "2001.00003", "sources": "s2_hub", "label": "C"},
        "paper:d": {"type": NodeType.PAPER, "arxiv_id": "2001.00004", "sources": "s2_hub", "label": "D"},
        "paper:e": {"type": NodeType.PAPER, "arxiv_id": "2001.00005", "sources": "s2_hub", "label": "E"},
        "paper:f": {"type": NodeType.PAPER, "arxiv_id": "2001.00006", "sources": "s2_other", "label": "F"},
        "person:x": {"type": NodeType.PERSON, "label": "X"},
    }
    for nid, data in papers.items():
        G.add_node(nid, **data)
    edges = [
        ("paper:b", "paper:a"),
        ("paper:c", "paper:a"),
        ("paper:d", "paper:b"),
        ("paper:e", "paper:b"),
        ("paper:f", "paper:c"),
    ]
    for u, v in edges:
        G.add_edge(u, v, type="CITES", source="s2_expanded")
    return G


def test_hub_scores_ranks_by_degree_and_filters_sources():
    G = _make_graph()
    top = _hub_scores(G, top_n=3, sources_filter="s2_hub")
    # Filtered to s2_hub only (excludes paper:f which has s2_other)
    aids = [aid for _, _, aid in top]
    assert "2001.00006" not in aids  # s2_other excluded
    assert len(aids) <= 3
    # Highest degree in s2_hub is paper:b (deg 2 via d,e after a,c deg1)
    assert top[0][0] == "paper:b" or top[0][2] == "2001.00002"


def test_hub_scores_without_filter_includes_all():
    G = _make_graph()
    top = _hub_scores(G, top_n=10, sources_filter="")
    aids = [aid for _, _, aid in top]
    assert "2001.00006" in aids  # s2_other included when no filter


def test_hub_guided_expander_checkpoint_resume(tmp_path):
    G = _make_graph()
    cp = str(tmp_path / "state.json")

    class FakeExpander:
        def expand_from_seeds(self, seed_arxiv_ids, graph, max_depth=1,
                              direction="both", label_source="s2_hub"):
            # Fake: no-op expansion, returns stats
            return {"papers_found": 0, "api_calls": 0, "edges_added": 0}

    hub = HubGuidedExpander(
        expander=FakeExpander(),
        top_k=3,
        sources_filter="s2_hub",
        checkpoint=cp,
    )
    result = hub.run(G, seeds=["2001.00001"], max_layers=2)
    assert result["layers_completed"] == 2
    assert os.path.exists(cp)

    # Checkpoint contains last layer + frontier
    with open(cp) as f:
        state = json.load(f)
    assert state["layer"] == 2
    assert isinstance(state["frontier"], list)


def test_hub_guided_expander_stops_on_empty_frontier(tmp_path):
    G = _make_graph()
    cp = str(tmp_path / "state2.json")

    class FakeExpander:
        def expand_from_seeds(self, seed_arxiv_ids, graph, max_depth=1,
                              direction="both", label_source="s2_hub"):
            return {"papers_found": 0, "api_calls": 0, "edges_added": 0}

    hub = HubGuidedExpander(
        expander=FakeExpander(),
        top_k=0,  # no papers kept → frontier empty → stop
        sources_filter="s2_hub",
        checkpoint=cp,
    )
    result = hub.run(G, seeds=["2001.00001"], max_layers=5)
    assert result["layers_completed"] == 1
