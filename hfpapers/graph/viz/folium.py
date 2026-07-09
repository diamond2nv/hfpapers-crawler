#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""folium-based interactive institution map.

Generates an HTML map with:
- MarkerCluster for institution nodes (auto-grouping at zoom)
- Popup with institution name, country, geo source
- Optional Folium HeatMap for density

Usage::

    from hfpapers.graph.viz.folium import render_institution_map

    render_institution_map(G, output="~/data/kg/institution_map.html")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from hfpapers.graph.schema import NodeType

logger = logging.getLogger("hfpapers.graph.viz.folium")

# ── Default output path ────────────────────────────────────────
DEFAULT_MAP = "~/data/kg/institution_map.html"


def render_institution_map(
    G: "nx.Graph",  # noqa: N802
    output: str = DEFAULT_MAP,
    map_center: Optional[list[float]] = None,
    zoom_start: int = 3,
) -> str:
    """Generate an interactive HTML map of all INSTITUTION nodes.

    Args:
        G: NetworkX knowledge graph (must have INSTITUTION nodes with lat/lng).
        output: Output HTML file path.
        map_center: [lat, lng] for initial map center.
            Defaults to China centroid (35, 105).
        zoom_start: Initial zoom level.

    Returns:
        Path to the generated HTML file.
    """
    import folium
    from folium.plugins import MarkerCluster

    center = map_center or [35.0, 105.0]
    m = folium.Map(location=center, zoom_start=zoom_start,
                   tiles="CartoDB Positron",
                   control_scale=True)

    cluster = MarkerCluster(
        name="Institutions",
        options={"spiderfyOnMaxZoom": True, "showCoverageOnHover": False},
    ).add_to(m)

    n_added = 0
    for nid, data in G.nodes(data=True):
        nt = data.get("type")
        if not nt or getattr(nt, "name", nt) != "INSTITUTION":
            continue

        lat = data.get("lat")
        lng = data.get("lng")
        if not lat or not lng:
            continue
        lat, lng = float(lat), float(lng)
        if lat == 0.0 and lng == 0.0:
            continue

        label = data.get("label", nid)[:80]
        country = data.get("country", "")
        city = data.get("city", "")
        geo_src = data.get("geo_source", "unknown")
        persons = _get_affiliated_persons(G, nid)

        popup_text = (
            f"<b>{label}</b><br>"
            f"{city}, {country}<br>"
            f"<small>source: {geo_src}</small>"
            f"<br><small>persons: {persons}</small>"
        )

        color = "#c084fc" if geo_src == "curated" else "#60a5fa"
        folium.Marker(
            location=[lat, lng],
            popup=folium.Popup(popup_text, max_width=300),
            icon=folium.Icon(color="purple" if geo_src == "curated" else "blue",
                             icon="university", prefix="fa"),
            tooltip=label[:50],
        ).add_to(cluster)
        n_added += 1

    # Layer control
    folium.LayerControl().add_to(m)

    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(path))

    logger.info("Map saved: %d institutions → %s", n_added, path)
    return str(path)


def _get_affiliated_persons(G: "nx.Graph", inst_id: str) -> str:  # noqa: N802
    """Return comma-separated list of person labels affiliated with an institution."""
    from hfpapers.graph.schema import EdgeType

    names = []
    for neighbor in G.neighbors(inst_id):
        edge_data = G.get_edge_data(inst_id, neighbor)
        if not edge_data:
            continue
        etype = edge_data.get("type") if isinstance(edge_data, dict) else None
        if etype is None:
            # MultiDiGraph: check all keys
            for ed in edge_data.values() if isinstance(edge_data, dict) else []:
                if ed.get("type") == EdgeType.AFFILIATED_WITH:
                    _add_person_name(G, neighbor, names)
                    break
        elif etype == EdgeType.AFFILIATED_WITH:
            _add_person_name(G, neighbor, names)
    return ", ".join(names[:5]) + ("..." if len(names) > 5 else "")


def _add_person_name(G: "nx.Graph", nid: str, names: list):  # noqa: N802
    """Append person label to names list if node is a PERSON."""
    nd = G.nodes.get(nid, {})
    nt = nd.get("type")
    if nt and getattr(nt, "name", nt) == "PERSON":
        label = nd.get("label", nid)[:30]
        if label not in names:
            names.append(label)
