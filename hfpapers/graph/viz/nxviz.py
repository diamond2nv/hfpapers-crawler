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


def render_citation_network(
    G: "nx.Graph",  # noqa: N802
    output: Optional[str] = None,
    figsize: tuple[int, int] = (16, 12),
    dpi: int = 150,
) -> Optional[str]:
    """Render a citation network graph with spring layout.

    Shows PAPER nodes with CITES edges. Node size proportional to
    citation count (in-degree of CITES edges).

    Args:
        G: Subgraph containing PAPER + CITES edges.
        output: Output image path (default: ~/data/kg/citation.png).
        figsize: Matplotlib figure size.
        dpi: Output DPI.

    Returns:
        Path to saved image, or None on failure.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import networkx as nx
        import numpy as np
    except ImportError:
        logger.warning("matplotlib not available — skipping citation plot")
        return None

    from hfpapers.graph.schema import EdgeType

    path = Path(output or "~/data/kg/citation.png").expanduser()

    # Filter to largest connected component
    if nx.number_connected_components(G) > 1:
        largest_cc = max(nx.connected_components(G), key=len)
        G = G.subgraph(largest_cc).copy()

    if G.number_of_nodes() < 3:
        logger.warning("Too few nodes (%d) for citation plot", G.number_of_nodes())
        return None

    # Spring layout (k inversely proportional to sqrt(n) for readability)
    k = 2.0 / np.sqrt(G.number_of_nodes())
    pos = nx.spring_layout(G, k=k, iterations=50, seed=42)

    fig, ax = plt.subplots(figsize=figsize)

    # Compute node sizes based on CITES in-degree
    in_degrees = {}
    for _, _, d in G.edges(data=True):
        et = d.get("type")
        et_name = getattr(et, "name", str(et)) if not isinstance(et, str) else str(et)
        # Count incoming CITES as citation count
        pass

    # Count CITED_BY in-degree
    cites_in = {}
    for u, v, d in G.edges(data=True):
        et = d.get("type")
        et_name = getattr(et, "name", str(et)) if not isinstance(et, str) else str(et)
        if et_name == "CITES":
            cites_in[v] = cites_in.get(v, 0) + 1

    max_cites = max(cites_in.values()) if cites_in else 1
    node_sizes = []
    node_colors = []
    for n in G.nodes():
        ci = cites_in.get(n, 0)
        size = 20 + 80 * (ci / max_cites) if max_cites > 0 else 30
        node_sizes.append(size)
        # Color: more citations = darker
        intensity = 0.3 + 0.5 * (ci / max_cites) if max_cites > 0 else 0.3
        node_colors.append((intensity, 0.6, 0.8, 0.8))  # blueish

    # Draw CITES edges as thin arrows
    cites_edges = []
    non_cites_edges = []
    for u, v, d in G.edges(data=True):
        et = d.get("type")
        et_name = getattr(et, "name", str(et)) if not isinstance(et, str) else str(et)
        if et_name == "CITES":
            cites_edges.append((u, v))
        else:
            non_cites_edges.append((u, v))

    nx.draw_networkx_edges(G, pos, edgelist=cites_edges, ax=ax,
                           alpha=0.15, edge_color="#888", width=0.3)
    if non_cites_edges:
        nx.draw_networkx_edges(G, pos, edgelist=non_cites_edges, ax=ax,
                               alpha=0.08, edge_color="#aaa", width=0.2)

    nx.draw_networkx_nodes(G, pos, ax=ax, node_size=node_sizes,
                           node_color=node_colors, edgecolors="white",
                           linewidths=0.3)

    # Label top-cited papers
    top_cited = sorted(cites_in.items(), key=lambda x: x[1], reverse=True)[:20]
    labels = {}
    for nid, _ in top_cited:
        label = G.nodes[nid].get("label", nid)
        # Truncate long labels
        labels[nid] = label[:40] if len(label) > 40 else label
    nx.draw_networkx_labels(G, pos, labels, ax=ax, font_size=5, alpha=0.7)

    ax.set_title(f"Citation Network — {G.number_of_nodes()} papers, "
                 f"{G.number_of_edges()} edges", fontsize=12)
    ax.axis("off")

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(path), dpi=dpi, bbox_inches="tight")
    plt.close(fig)

    logger.info("Citation network saved: %d nodes → %s", G.number_of_nodes(), path)
    return str(path)


def render_circos(
    G: "nx.Graph",  # noqa: N802
    output: Optional[str] = None,
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
                Defaults to ~/data/kg/circos.png when None or empty.
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

    path = Path(output or DEFAULT_CIRCOS).expanduser()
    sub = _build_person_institution_subgraph(G, group_by)
    if sub.number_of_nodes() < 3:
        logger.warning("Too few nodes (%d) for a circular plot", sub.number_of_nodes())
        return None

    fig, ax = plt.subplots(figsize=figsize, subplot_kw={"projection": "polar"})
    _circular_layout(sub, ax, group_by=group_by)
    fig.suptitle(f"Co-authorship Network — {sub.number_of_nodes()} nodes, "
                 f"{sub.number_of_edges()} edges", fontsize=14, y=1.02)
    plt.tight_layout()

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
        label = G.nodes[nid].get("label", nid)
        if tname == "INSTITUTION":
            label = G.nodes[nid].get("abbrev", label)
        size = 100 if tname == "INSTITUTION" else 40
        ax.scatter(a, r, s=size, color=c, edgecolors="white",
                   linewidth=0.3, zorder=5, alpha=0.9)

        # Angle-aware text placement — push labels outward to avoid clipping
        label_r = 1.1  # place labels beyond the node ring
        fontsize = 8 if tname == "INSTITUTION" else 4
        cos_a = np.cos(a)
        if cos_a < 0:
            # Left half: right-align, offset left
            ha, dx = "right", (-8, 0)
        elif cos_a > 0:
            # Right half: left-align, offset right
            ha, dx = "left", (8, 0)
        else:
            ha, dx = "center", (0, 8)
        ax.annotate(label, (a, label_r), textcoords="offset points",
                    xytext=dx, fontsize=fontsize, ha=ha,
                    va="center", alpha=0.8,
                    fontfamily="sans-serif",
                    clip_on=False)

    ax.set_ylim(0, 1.4)
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
