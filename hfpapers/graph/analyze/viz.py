#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analysis visualizations — publication-quality vector figures for QMD reports.

Generates PDF/SVG figures to be embedded in Quarto documents:

- ``render_community_graph()``: Citation network colored by community
- ``render_impact_chart()``: Horizontal bar chart of top cited papers
- ``render_algorithm_comparison()``: Side-by-side community detection panels
- ``render_community_sizes()``: Community size bar chart
- ``render_bridge_network()``: Author bridge network
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("hfpapers.graph.analyze.viz")

# Color palette (8 distinct + 1 gray for misc)
COMMUNITY_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
    "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
    "#bcbd22", "#17becf",
]
GRAY = "#cccccc"


def _ensure_matplotlib():
    """Import matplotlib, return (plt, np) or None."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        return plt, np
    except ImportError:
        logger.warning("matplotlib not available")
        return None, None


def render_community_graph(
    citation_H: "nx.DiGraph",
    communities: list[set],
    output: str,
    figsize: tuple = (14, 10),
    dpi: int = 150,
) -> Optional[str]:
    """Render citation network with nodes colored by community.

    Args:
        citation_H: Directed citation graph (from subgraph.citation_subgraph).
        communities: List of node sets from community detection.
        output: Output path (PDF/SVG recommended for QMD).
        figsize: Figure dimensions.
        dpi: Output resolution.

    Returns:
        Path to saved figure, or None on failure.
    """
    plt, np = _ensure_matplotlib()
    if plt is None:
        return None
    import networkx as nx

    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Build community lookup
    node_to_community: dict[str, int] = {}
    for ci, comm in enumerate(communities):
        for n in comm:
            node_to_community[n] = ci

    # Filter to largest CC for layout
    Hu = citation_H.to_undirected()
    if Hu.number_of_nodes() < 3:
        return None
    cc = sorted(nx.connected_components(Hu), key=len, reverse=True)
    Hu_lcc = Hu.subgraph(cc[0]).copy()

    # Layout
    k = 3.0 / np.sqrt(Hu_lcc.number_of_nodes())
    pos = nx.spring_layout(Hu_lcc, k=k, iterations=100, seed=42)

    # Assign colors
    colors = []
    sizes = []
    for n in Hu_lcc.nodes():
        ci = node_to_community.get(n, -1)
        if 0 <= ci < len(COMMUNITY_COLORS):
            colors.append(COMMUNITY_COLORS[ci])
        else:
            colors.append(GRAY)
        # Size by citation in-degree
        in_deg = citation_H.in_degree(n) if n in citation_H else 0
        sizes.append(max(10, min(in_deg * 18 + 20, 200)))

    fig, ax = plt.subplots(figsize=figsize)

    # Edges (gray, thin)
    nx.draw_networkx_edges(
        Hu_lcc, pos, ax=ax,
        alpha=0.15, edge_color=GRAY, width=0.3,
    )

    # Nodes
    nx.draw_networkx_nodes(
        Hu_lcc, pos, ax=ax,
        node_color=colors, node_size=sizes,
        edgecolors="white", linewidths=0.3,
        alpha=0.85,
    )

    # Legend for communities
    legend_elements = []
    for ci in sorted(set(node_to_community.get(n, -1) for n in Hu_lcc.nodes())):
        if ci >= 0:
            from matplotlib.patches import Patch
            label = f"C{ci+1}" if ci < len(COMMUNITY_COLORS) else "Other"
            legend_elements.append(
                Patch(facecolor=COMMUNITY_COLORS[ci % len(COMMUNITY_COLORS)],
                      label=label, alpha=0.85)
            )
    ax.legend(handles=legend_elements, loc="upper right", fontsize=8,
              title="Communities", title_fontsize=9, framealpha=0.9)

    ax.set_title(f"Citation Network — {Hu_lcc.number_of_nodes()} papers, "
                 f"{len(communities)} communities",
                 fontsize=12, pad=10)
    ax.axis("off")

    fig.savefig(str(path), format=path.suffix.lstrip("."), dpi=dpi,
                bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)
    logger.info("Community graph saved to %s", path)
    return str(path)


def render_impact_chart(
    impact_results: dict[str, Any],
    output: str,
    top_n: int = 15,
    figsize: tuple = (10, 8),
    dpi: int = 150,
) -> Optional[str]:
    """Render a horizontal bar chart of top cited papers.

    Args:
        impact_results: From impact.full_impact_report().
        output: Output path (PDF/SVG).
        top_n: Number of papers to show.
        figsize: Figure dimensions.
        dpi: Output resolution.

    Returns:
        Path to saved figure, or None.
    """
    plt, np = _ensure_matplotlib()
    if plt is None:
        return None

    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    degree = impact_results.get("degree", [])[:top_n]
    betweenness = impact_results.get("betweenness", [])[:top_n]
    pagerank = impact_results.get("pagerank", [])[:top_n]

    # Determine which data to show
    sources = []
    if degree:
        sources.append(("Cited By (in-degree)", degree, "#1f77b4"))
    if pagerank and pagerank != degree:
        sources.append(("PageRank", pagerank, "#ff7f0e"))
    if betweenness:
        sources.append(("Betweenness", betweenness, "#2ca02c"))

    n_plots = len(sources)
    if n_plots == 0:
        return None

    fig, axes = plt.subplots(1, n_plots, figsize=(figsize[0] * n_plots, figsize[1]))
    if n_plots == 1:
        axes = [axes]

    for ax, (title, data, color) in zip(axes, sources):
        labels = []
        scores = []
        for item in data:
            label = str(item.get("label", item.get("name", "?")))[:55]
            labels.append(label)
            score_key = [k for k in ("cited_by", "pagerank", "betweenness", "authority_score")
                        if k in item]
            scores.append(float(item.get(score_key[0], 0)) if score_key else 0)

        y_pos = range(len(labels))
        ax.barh(y_pos, scores, color=color, alpha=0.8, height=0.6)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=7)
        ax.invert_yaxis()
        ax.set_xlabel("Score", fontsize=9)
        ax.set_title(title, fontsize=10, fontweight="bold")
        ax.tick_params(axis="y", labelsize=7)

    fig.tight_layout(pad=1.5)
    fig.savefig(str(path), format=path.suffix.lstrip("."), dpi=dpi,
                bbox_inches="tight")
    plt.close(fig)
    logger.info("Impact chart saved to %s", path)
    return str(path)


def render_algorithm_comparison(
    citation_H: "nx.DiGraph",
    community_results: dict[str, Any],
    output: str,
    figsize: tuple = (18, 6),
    dpi: int = 150,
) -> Optional[str]:
    """Render side-by-side community detection algorithm comparison.

    Shows Louvain, Label Propagation, and Leiden results on the same
    citation network layout, so the user can visually compare divisions.

    Args:
        citation_H: Directed citation graph.
        community_results: From communities.run_all().
        output: Output path (PDF/SVG).
        figsize: Figure dimensions.
        dpi: Output resolution.

    Returns:
        Path to saved figure, or None.
    """
    plt, np = _ensure_matplotlib()
    if plt is None:
        return None
    import networkx as nx

    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    Hu = citation_H.to_undirected()
    cc = sorted(nx.connected_components(Hu), key=len, reverse=True)
    if not cc:
        return None
    Hu_lcc = Hu.subgraph(cc[0]).copy()

    # Layout (shared across all panels)
    k = 3.0 / np.sqrt(Hu_lcc.number_of_nodes())
    pos = nx.spring_layout(Hu_lcc, k=k, iterations=100, seed=42)

    # Collect community sets from each algorithm
    alg_results: list[tuple[str, list[set]]] = []
    for alg_name in ("louvain", "leiden", "label_propagation"):
        alg_data = community_results.get(alg_name, {})
        if "error" not in alg_data and alg_data.get("communities"):
            # Need to reconstruct sets from descriptions — we don't have raw sets.
            # Instead, use the num_communities count as fallback info
            alg_results.append((alg_name.capitalize(), alg_data.get("num_communities", 0)))
        else:
            alg_results.append((alg_name.capitalize(), 0))

    # For actual community sets, re-run on LCC
    from hfpapers.graph.analyze import communities as comm_module

    try:
        louvain_sets = comm_module.louvain(Hu_lcc)
    except Exception:
        louvain_sets = []

    try:
        leiden_sets = comm_module.leiden(Hu_lcc)
    except Exception:
        leiden_sets = []

    try:
        label_sets = comm_module.label_propagation(Hu_lcc)
    except Exception:
        label_sets = []

    algo_sets = [
        ("Louvain", louvain_sets),
        ("Leiden", leiden_sets),
        ("Label Propagation", label_sets),
    ]

    n_valid = sum(1 for _, s in algo_sets if s)
    if n_valid == 0:
        return None

    fig, axes = plt.subplots(1, n_valid, figsize=(figsize[0], figsize[1]))
    if n_valid == 1:
        axes = [axes]

    for ax, (name, sets) in zip(axes, [a for a in algo_sets if a[1]]):
        # Build color mapping
        node_color: dict[str, int] = {}
        for ci, s in enumerate(sets):
            for n in s:
                if n in Hu_lcc:
                    node_color[n] = ci

        colors = [COMMUNITY_COLORS[node_color.get(n, -1) % len(COMMUNITY_COLORS)]
                  for n in Hu_lcc.nodes()]

        nx.draw_networkx_edges(Hu_lcc, pos, ax=ax, alpha=0.1, edge_color=GRAY, width=0.3)
        nx.draw_networkx_nodes(
            Hu_lcc, pos, ax=ax,
            node_color=colors, node_size=12,
            edgecolors="white", linewidths=0.2,
            alpha=0.85,
        )
        ax.set_title(f"{name}\n({len(sets)} communities)", fontsize=10, fontweight="bold")
        ax.axis("off")

    fig.suptitle("Community Detection Algorithm Comparison", fontsize=13, y=1.02)
    fig.tight_layout()
    fig.savefig(str(path), format=path.suffix.lstrip("."), dpi=dpi,
                bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)
    logger.info("Algorithm comparison saved to %s", path)
    return str(path)


def render_community_sizes(
    community_results: dict[str, Any],
    output: str,
    figsize: tuple = (8, 5),
    dpi: int = 150,
) -> Optional[str]:
    """Render a bar chart of community sizes.

    Args:
        community_results: From communities.full_report().
        output: Output path (PDF/SVG).
        figsize: Figure dimensions.
        dpi: Output resolution.

    Returns:
        Path to saved figure, or None.
    """
    plt, np = _ensure_matplotlib()
    if plt is None:
        return None

    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    communities_data = community_results.get("communities", [])
    if not communities_data:
        return None

    sizes = [c.get("size", 0) for c in communities_data]
    labels = [f"C{c.get('id', i+1)}" for i, c in enumerate(communities_data)]
    kw_counts = [", ".join(c.get("keywords", [])[:3]) for c in communities_data]

    fig, ax = plt.subplots(figsize=figsize)

    colors = [COMMUNITY_COLORS[i % len(COMMUNITY_COLORS)] for i in range(len(sizes))]
    bars = ax.bar(labels, sizes, color=colors, alpha=0.8, edgecolor="white", width=0.6)

    # Annotate
    for bar, kw in zip(bars, kw_counts):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            kw, ha="center", va="bottom",
            fontsize=6, rotation=45,
        )

    ax.set_ylabel("Papers", fontsize=10)
    ax.set_title("Community Sizes", fontsize=12, fontweight="bold")
    ax.tick_params(axis="x", labelsize=9)

    fig.tight_layout()
    fig.savefig(str(path), format=path.suffix.lstrip("."), dpi=dpi,
                bbox_inches="tight")
    plt.close(fig)
    logger.info("Community sizes chart saved to %s", path)
    return str(path)


def render_all(
    citation_H: "nx.DiGraph",
    impact_results: dict[str, Any],
    community_results: dict[str, Any],
    output_dir: str = "~/data/kg/figures/",
) -> dict[str, str]:
    """Render all analysis visualizations.

    Args:
        citation_H: Directed citation subgraph.
        impact_results: From impact.full_impact_report().
        community_results: From communities.full_report().
        output_dir: Directory to save figures.

    Returns:
        Dict: {figure_name: file_path}
    """
    out_dir = Path(output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    figures = {}

    # Need raw community sets for community graph rendering
    # We need to re-run the preferred algorithm on the LCC
    Hu = citation_H.to_undirected()
    import networkx as nx
    cc = sorted(nx.connected_components(Hu), key=len, reverse=True)
    if cc:
        Hu_lcc = Hu.subgraph(cc[0]).copy()
        from hfpapers.graph.analyze import communities as comm_module
        try:
            preferred_sets = comm_module.leiden(Hu_lcc)
        except Exception:
            preferred_sets = comm_module.louvain(Hu_lcc)

        # Community graph
        fig_path = str(out_dir / "community_graph.pdf")
        result = render_community_graph(citation_H, preferred_sets, fig_path)
        if result:
            figures["community_graph"] = result

        # Algorithm comparison
        fig_path = str(out_dir / "algorithm_comparison.pdf")
        result = render_algorithm_comparison(citation_H, community_results, fig_path)
        if result:
            figures["algorithm_comparison"] = result

    # Impact chart
    fig_path = str(out_dir / "impact_ranking.pdf")
    result = render_impact_chart(impact_results, fig_path)
    if result:
        figures["impact_ranking"] = result

    # Community sizes
    fig_path = str(out_dir / "community_sizes.pdf")
    result = render_community_sizes(community_results, fig_path)
    if result:
        figures["community_sizes"] = result

    logger.info("Rendered %d figures to %s", len(figures), out_dir)
    return figures
