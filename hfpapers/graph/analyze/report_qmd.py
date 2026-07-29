#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QMD report generator — Quarto docs with Python code appendix + pre-generated vector figures.

The QMD references pre-generated PDF figures (from viz.py) for the actual report,
and includes the Python plotting code as non-executable code blocks for transparency.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("hfpapers.graph.analyze.report_qmd")

COMMUNITY_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
    "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
    "#bcbd22", "#17becf",
]


def _code_block(body: str, label: str = "") -> str:
    lbl = f" #{label}" if label else ""
    return f"```python{lbl}\n{body}\n```\n\n"


def _fig_ref(key: str, caption: str, label: str = "", width: str = "80%") -> str:
    lbl = f" #fig-{label}" if label else ""
    return f"![{caption}]({key}){{width={width}{lbl}}}\n\n"


def _setup_block() -> str:
    return _code_block(
        'import json, pathlib\n'
        'import matplotlib.pyplot as plt\n'
        'import networkx as nx\n'
        'import numpy as np\n'
        '\n'
        '# Color palette\n'
        f'CCOLORS = {json.dumps(COMMUNITY_COLORS)}\n'
        'GRAY = "#cccccc"\n',
        label=".setup",
    )


def _impact_block() -> str:
    return _code_block(
        'fig, ax = plt.subplots(figsize=(10, 6))\n'
        'labels = [d["label"][:55] for d in impact["degree"][:15]]\n'
        'scores = [d["cited_by"] for d in impact["degree"][:15]]\n'
        'ax.barh(range(len(labels)), scores, color="#1f77b4", alpha=0.85, height=0.6)\n'
        'ax.set_yticks(range(len(labels)))\n'
        'ax.set_yticklabels(labels, fontsize=7)\n'
        'ax.invert_yaxis()\n'
        'ax.set_xlabel("Times cited within network", fontsize=9)\n'
        'fig.tight_layout()\n'
    )


def _community_graph_block() -> str:
    return _code_block(
        '# pos = pre-computed spring layout (fixed seed=42)\n'
        'node_to_community = {...}  # from community detection\n'
        '\n'
        'colors = [CCOLORS.get(node_to_community.get(n, -1), GRAY)\n'
        '          for n in lcc_nodes]\n'
        'fig, ax = plt.subplots(figsize=(12, 8))\n'
        'for u, v in edges:\n'
        '    ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]],\n'
        '            color=GRAY, alpha=0.12, linewidth=0.3)\n'
        'ax.scatter(xs, ys, c=colors, s=15, alpha=0.85, edgecolors="white")\n'
        'ax.axis("off")\n'
        'fig.tight_layout()\n'
    )


def _algo_compare_block() -> str:
    return _code_block(
        '# Same layout, different community coloring\n'
        'fig, axes = plt.subplots(1, 3, figsize=(18, 5.5))\n'
        'for ax, (name, nc) in zip(axes, [("Louvain", 8), ("Leiden", 8), ("Label Prop.", 12)]):\n'
        '    # ... plot edges and nodes colored by algorithm communities ...\n'
        '    ax.set_title(f"{name}\\n({nc} communities)", fontsize=10)\n'
        '    ax.axis("off")\n'
        'fig.tight_layout()\n'
    )


def _community_sizes_block() -> str:
    return _code_block(
        'fig, ax = plt.subplots(figsize=(8, 4))\n'
        'colors = [CCOLORS[i] for i in range(len(sizes))]\n'
        'ax.bar(cids, sizes, color=colors, alpha=0.85, edgecolor="white")\n'
        'for bar, kw in zip(bars, kws):\n'
        '    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,\n'
        '            kw, ha="center", fontsize=6, rotation=30)\n'
        'ax.set_ylabel("Papers")\n'
        'fig.tight_layout()\n'
    )


def generate_qmd(
    source: str = "coc",
    figures: dict[str, str] | None = None,
    title: str = "",
    output_path: str = "",
) -> str:
    """Generate a QMD document with Python code appendix + pre-generated figures.

    Args:
        source: Source tag analyzed.
        figures: Dict of {figure_name: file_path} from viz.render_all().
        title: Report title.
        output_path: Where to save the QMD file.

    Returns:
        QMD content.
    """
    if not output_path:
        output_path = f"~/data/kg/{source}-report.qmd"
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    dt = datetime.now().strftime('%Y-%m-%d %H:%M')
    qmd_title = title or f"Knowledge Graph Analysis: {source}"

    # Make figure paths relative to QMD
    fig_rel: dict[str, str] = {}
    if figures:
        qmd_dir = path.parent
        for key, fp in figures.items():
            try:
                fig_rel[key] = str(Path(fp).relative_to(qmd_dir))
            except ValueError:
                fig_rel[key] = fp

    lines: list[str] = [
        # ── YAML frontmatter ──
        "---\n",
        f'title: "{qmd_title}"\n',
        f'subtitle: "Source: {source} | {dt}"\n',
        'format:\n',
        '  pdf:\n',
        '    papersize: a4\n',
        '    margin-left: 2cm\n',
        '    margin-right: 2cm\n',
        '    margin-top: 2cm\n',
        '    margin-bottom: 2cm\n',
        '    toc: true\n',
        '    toc-depth: 3\n',
        '    number-sections: true\n',
        '    colorlinks: true\n',
        '    fontsize: 10pt\n',
        '    mainfont: Liberation Serif\n',
        '    monofont: Liberation Mono\n',
        '    include-in-header:\n',
        '      text: |\n',
        '        \\usepackage{booktabs}\n',
        '        \\usepackage{longtable}\n',
        '        \\usepackage{caption}\n',
        '        \\captionsetup{font=small,labelfont=bf}\n',
        '---\n',
        '\n',
        '\n',
        # ── 1. Network Overview ──
        '## Network Overview\n',
        '\n',
        '*This section populated by `hfpclawer graph analyze`.*\n',
        '\n',
        # ── 2. Impact Analysis ──
        '## Top Cited Papers\n',
        '\n',
    ]

    if "impact_ranking" in fig_rel:
        lines.append(_fig_ref(fig_rel["impact_ranking"],
            "Top cited papers by in-degree and betweenness", "impact", width="100%"))

    lines.append(
        f"The chart above shows papers ranked by in-degree (times cited within "
        f"the {source} citation network) and by betweenness centrality.\n\n"
    )

    # ── 3. Community Analysis ──
    lines.append("## Research Communities\n\n")

    if "community_graph" in fig_rel:
        lines.append(_fig_ref(fig_rel["community_graph"],
            "Citation network colored by research community", "communities", width="90%"))

    if "algorithm_comparison" in fig_rel:
        lines.append(_fig_ref(fig_rel["algorithm_comparison"],
            "Algorithm comparison: Louvain / Leiden / Label Propagation on same layout",
            "algo-compare", width="100%"))

    if "community_sizes" in fig_rel:
        lines.append(_fig_ref(fig_rel["community_sizes"],
            "Community sizes with topic keywords", "sizes", width="70%"))

    # ── 4. Python code appendix ──
    lines.extend([
        '\n',
        '## Appendix: Plotting Code\n',
        '\n',
        'The following Python code was used to generate the figures in this report.\n',
        '\n',
        '### Setup\n',
        '\n',
        _setup_block(),
        '### Impact Bar Chart\n',
        '\n',
        _impact_block(),
        '### Community Graph\n',
        '\n',
        _community_graph_block(),
        '### Algorithm Comparison\n',
        '\n',
        _algo_compare_block(),
        '### Community Sizes\n',
        '\n',
        _community_sizes_block(),
    ])

    # ── 5. Methodology ──
    lines.extend([
        '## Methodology\n',
        '\n',
        '### Impact Metrics\n',
        '\n',
        "- **Degree (in-degree)**: Times cited within the network.\n",
        "- **Betweenness Centrality**: Paper as connector between sub-communities.\n",
        '\n',
        '### Community Detection\n',
        '\n',
        "- **Louvain**: Greedy modularity maximisation. Fast. May merge small communities.\n",
        "- **Leiden**: Louvain improvement - guarantees connected communities.\n",
        "- **Label Propagation**: Fast, non-deterministic, finds finer divisions.\n",
        '\n',
        '### Bridge Detection\n',
        '\n',
        "An author is a **bridge** if their papers span 2+ distinct communities.\n",
        "This indicates cross-pollination between sub-fields.\n",
        '\n',
    ])

    qmd = "".join(lines)
    path.write_text(qmd, encoding="utf-8")
    logger.info("QMD report saved to %s", path)
    return qmd
