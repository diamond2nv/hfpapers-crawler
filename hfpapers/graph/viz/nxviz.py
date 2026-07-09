#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""nxviz-based graph visualization — Circos, Arc, and Hive plots.

Generates static PNG/SVG images using matplotlib + nxviz.
Falls back gracefully if nxviz or matplotlib is unavailable.

Usage::

    from hfpapers.graph.viz.nxviz import render_circos

    render_circos(G, output="~/data/kg/circos.png", group_by="country")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from hfpapers.graph.schema import NodeType

logger = logging.getLogger("hfpapers.graph.viz.nxviz")

# ── Defaults ───────────────────────────────────────────────────
DEFAULT_CIRCOS = "~/data/kg/circos.png"


def render_circos(
    G: "nx.Graph",  # noqa: N802
    output: str = DEFAULT_CIRCOS,
    group_by: str = "country",
    sort_by: str = "label",
    figsize: tuple[int, int] = (12, 12),
    dpi: int = 150,
) -> Optional[str]:
    """Generate a circular layout plot of person and institution nodes.

    Uses matplotlib circular layout (not nxviz Circos) for robustness.
    nxviz is NOT required — pure matplotlib implementation.

    Args:
        G: Knowledge graph.
        output: Output image path (PNG or SVG via extension).
        group_by: Node attribute to color by.
        sort_by: Node attribute to sort within groups.
        figsize: Matplotlib figure size.
        dpi: Output DPI.

    Returns:
        Path to the generated image, or None if matplotlib unavailable.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not available — skipping circular plot")
        return None

    sub = _build_person_institution_subgraph(G, group_by)
    if sub.number_of_nodes() < 3:
        logger.warning("Too few nodes (%d) for a circular plot", sub.number_of_nodes())
        return None

    fig, ax = plt.subplots(figsize=figsize, subplot_kw={"projection": "polar"})
    _circular_layout(sub, ax, group_by=group_by)
    fig.suptitle(f"Co-authorship Network — {sub.number_of_nodes()} nodes, "
                 f"{sub.number_of_edges()} edges", fontsize=14, y=1.02)
    plt.tight_layout()

    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(path), dpi=dpi, bbox_inches="tight")
    plt.close(fig)

    logger.info("Circular plot saved: %d nodes → %s", sub.number_of_nodes(), path)
    return str(path)


def _circular_layout(G: "nx.Graph", ax, group_by: str = "type") -> None:  # noqa: N802
    """Draw a circular layout graph using matplotlib polar projection.

    Colors by node type (PERSON=blue, INSTITUTION=purple).
    Larger nodes for institutions, smaller for persons.
    """
    import matplotlib.pyplot as plt
    import networkx as nx
    import numpy as np

    # Filter to largest connected component for clearer visualization
    if nx.number_connected_components(G) > 1:
        largest_cc = max(nx.connected_components(G), key=len)
        G = G.subgraph(largest_cc).copy()

    nodes = list(G.nodes())
    n = len(nodes)
    if n == 0:
        return

    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    pos = {nodes[i]: (angles[i], 1) for i in range(n)}

    # Color by node type
    type_colors = {"PERSON": "#4a9eff", "INSTITUTION": "#c084fc"}

    for u, v in G.edges():
        if u in pos and v in pos:
            a1, r1 = pos[u]
            a2, r2 = pos[v]
            # Lighter edges for person-person, darker for person-institution
            edge_alpha = 0.15
            ax.plot([a1, a2], [r1, r2], color="#888888",
                    linewidth=0.2, alpha=edge_alpha)

    for nid in nodes:
        a, r = pos[nid]
        nt = G.nodes[nid].get("type", "")
        tname = getattr(nt, "name", nt) if not isinstance(nt, str) else nt
        c = type_colors.get(tname, "#888888")
        label = G.nodes[nid].get("label", nid)[:20]
        size = 100 if tname == "INSTITUTION" else 40
        ax.scatter(a, r, s=size, color=c, edgecolors="white",
                   linewidth=0.3, zorder=5, alpha=0.9)
        fontsize = 7 if tname == "INSTITUTION" else 4
        ax.annotate(label, (a, r), textcoords="offset points",
                    xytext=(0, 6), fontsize=fontsize, ha="center",
                    alpha=0.8, fontfamily="sans-serif")

    ax.set_ylim(0, 1.3)
    ax.set_yticks([])
    ax.set_xticks([])
    ax.set_frame_on(False)


def _build_person_institution_subgraph(G: "nx.Graph", group_by: str) -> "nx.Graph":  # noqa: N802
    """Extract a subgraph of PERSON + INSTITUTION nodes for viz."""
    import networkx as nx

    sub = nx.Graph()
    for nid, data in G.nodes(data=True):
        nt = data.get("type")
        if not nt:
            continue
        tname = getattr(nt, "name", nt)
        if tname not in ("PERSON", "INSTITUTION"):
            continue
        attrs = dict(data)
        attrs["type"] = tname  # Ensure string type for nxviz
        sub.add_node(nid, **attrs)

    for u, v, data in G.edges(data=True):
        if u in sub and v in sub:
            sub.add_edge(u, v, **(dict(data) if data else {}))

    return sub


def _node_attrs(G: "nx.Graph") -> set[str]:  # noqa: N802
    """Return set of common node attribute names across all nodes."""
    attrs: set[str] = set()
    for _, data in G.nodes(data=True):
        attrs.update(data.keys())
    return attrs


def _fallback_spring_plot(G: "nx.Graph", ax) -> None:  # noqa: N802
    """Fallback to spring layout if nxviz Circos fails."""
    import networkx as nx

    pos = nx.spring_layout(G, k=0.5, iterations=50, seed=42)
    nx.draw_networkx_nodes(G, pos, ax=ax, node_size=200,
                           node_color="#4a9eff", alpha=0.8)
    nx.draw_networkx_edges(G, pos, ax=ax, alpha=0.3, width=0.5)
    labels = {n: G.nodes[n].get("label", n)[:20] for n in G.nodes()}
    nx.draw_networkx_labels(G, pos, labels, ax=ax, font_size=8)
