#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Report formatting — convert analysis results to human-readable output.

Supports:
- Markdown report (default) — for CLI display and file export
- JSON — for programmatic consumption
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger("hfpapers.graph.analyze.report")


def _fmt_list(items: list[dict], key: str = "label") -> str:
    """Format a ranked list as markdown."""
    lines = []
    for i, item in enumerate(items, 1):
        label = item.get(key, item.get("label", item.get("name", "?")))
        lines.append(f"{i:2d}. **{label[:90]}**")
        # Show algorithm-specific score
        for score_key in ("cited_by", "pagerank", "betweenness", "authority_score",
                          "hub_score", "total_cites", "num_papers", "num_communities"):
            if score_key in item:
                lines[-1] = (
                    f"{i:2d}. [{item[score_key]}] **{label[:90]}**"
                )
                break
        # Extra info
        extras = []
        for ek in ("arxiv", "year", "num_papers", "num_communities"):
            val = item.get(ek)
            if val and str(val) not in ("0", "Unknown", ""):
                extras.append(f"{ek}={val}")
        if extras:
            lines.append(f"     {', '.join(extras)}")
    return "\n".join(lines)


def markdown_report(
    impact: dict[str, Any],
    communities: dict[str, Any],
    actors: dict[str, Any],
    title: str = "Knowledge Graph Analysis",
    source: str = "",
) -> str:
    """Generate a complete Markdown analysis report.

    Args:
        impact: Output from impact.full_impact_report().
        communities: Output from communities.full_report().
        actors: Output from actors.full_report().
        title: Report title.
        source: Source tag analyzed.

    Returns:
        Markdown string.
    """
    lines = [
        f"# {title}",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    if source:
        lines.append(f"**Source filter:** `{source}`")

    # ── Overview stats ──
    stats = impact.get("stats", {})
    lines.extend([
        "",
        "## 📊 Network Overview",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Papers | {stats.get('total_papers', '?'):,} |",
        f"| Citations (internal) | {stats.get('total_citations', '?'):,} |",
        f"| Authors | {actors.get('stats', {}).get('total_authors', '?'):,} |",
    ])

    # ── Impact: Degree ──
    degree = impact.get("degree", [])
    if degree:
        lines.extend([
            "",
            "## 🏆 Top Cited Papers (by in-degree)",
            "",
            _fmt_list(degree),
        ])

    # ── Impact: PageRank ──
    pagerank = impact.get("pagerank", [])
    if pagerank and pagerank != degree:
        lines.extend([
            "",
            "## 🌟 Top Papers by PageRank",
            "",
            _fmt_list(pagerank, key="label"),
        ])

    # ── Impact: Betweenness (bridges) ──
    betweenness = impact.get("betweenness", [])
    if betweenness and betweenness[0].get("betweenness", 0) > 0:
        lines.extend([
            "",
            "## 🌉 Top Bridge Papers (by betweenness)",
            "",
            _fmt_list(betweenness, key="label"),
        ])

    # ── Impact: HITS ──
    auth = impact.get("authorities", [])
    hubs = impact.get("hubs", [])
    if auth:
        lines.extend([
            "",
            "## 📚 Core Papers (HITS Authorities)",
            "",
            "Papers that are most cited — the foundational works.",
            "",
            _fmt_list(auth, key="label"),
        ])
    if hubs:
        lines.extend([
            "",
            "## 🔍 Survey Papers (HITS Hubs)",
            "",
            "Papers that cite many others — reviews and surveys.",
            "",
            _fmt_list(hubs, key="label"),
        ])

    # ── Impact: Author impact ──
    author_impact = impact.get("author_impact", [])
    if author_impact:
        lines.extend([
            "",
            "## 👥 Most Cited Authors",
            "",
            _fmt_list(author_impact, key="name"),
        ])

    # ── Communities ──
    num_comm = communities.get("num_communities", 0)
    if num_comm > 0:
        lines.extend([
            "",
            f"## 🔬 Research Communities ({num_comm})",
            "",
            f"**Algorithm:** {communities.get('algorithm', '?')} | "
            f"**LCC:** {communities.get('lcc_nodes', '?'):,} nodes | "
            f"**Sizes:** {', '.join(str(s) for s in communities.get('sizes', []))}",
            "",
        ])

        for comm in communities.get("communities", []):
            cid = comm.get("id", "?")
            size = comm.get("size", 0)
            keywords = comm.get("keywords", [])
            top = comm.get("top_papers", [])
            lines.extend([
                f"### Community {cid} ({size} papers)",
                "",
            ])
            if keywords:
                lines.append(f"**Topics:** `{'` `'.join(keywords)}`")
                lines.append("")
            if top:
                lines.append("**Top cited within community:**")
                lines.append("")
                for p in top:
                    lbl = p.get("label", "?")
                    c = p.get("cites_within", 0)
                    lines.append(f"- [{c}c] {lbl[:80]}")
                lines.append("")

    # ── Actors ──
    prolific = actors.get("prolific_authors", [])
    if prolific:
        lines.extend([
            "## 👥 Prolific Authors",
            "",
            "| # | Author | Papers |",
            "|---|--------|:------:|",
        ])
        for i, a in enumerate(prolific[:10], 1):
            lines.append(f"| {i} | {a.get('name', '?')} | {a.get('num_papers', 0)} |")
        lines.append("")

    bridge = actors.get("bridge_authors", [])
    if bridge:
        lines.extend([
            "## 🌉 Bridge Authors (cross-community)",
            "",
            f"Found **{len(bridge)}** authors spanning 2+ communities.",
            "",
            "| # | Author | Papers | Communities |",
            "|---|--------|:------:|:-----------:|",
        ])
        for i, b in enumerate(bridge[:10], 1):
            comms_str = ", ".join(str(c) for c in b.get("communities", []))
            lines.append(
                f"| {i} | {b.get('name', '?')} | "
                f"{b.get('num_papers', 0)} | {comms_str} |"
            )
        lines.append("")
    else:
        lines.extend([
            "## 🌉 Bridge Authors",
            "",
            "**No bridge authors found.** All authors work within a single ",
            "research community — no cross-community collaboration detected.",
            "",
        ])

    return "\n".join(lines)


def json_report(
    impact: dict[str, Any],
    communities: dict[str, Any],
    actors: dict[str, Any],
) -> str:
    """Serialize full analysis report as JSON."""
    report = {
        "meta": {
            "generated": datetime.now().isoformat(),
        },
        "impact": impact,
        "communities": communities,
        "actors": actors,
    }
    return json.dumps(report, indent=2, ensure_ascii=False, default=str)
