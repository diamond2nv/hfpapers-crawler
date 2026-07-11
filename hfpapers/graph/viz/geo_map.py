#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Community-overlaid geographic maps — interactive (folium) and static (cartopy).

Maps literature communities onto the world, showing:
  - Institution/city markers colored by dominant research community
  - Marker size proportional to affiliated papers
  - Geodesic collaboration edges between locations
  - Popup with community composition details

Usage::

    from hfpapers.graph.viz.geo_map import (
        render_community_folium,
        render_community_static,
        aggregate_institution_communities,
    )

    comm_map = aggregate_institution_communities(G)
    render_community_folium(G, comm_map, output="~/data/kg/community_map.html")
"""

from __future__ import annotations

import colorsys
import logging
from pathlib import Path
from typing import Optional

from hfpapers.graph.schema import EdgeType, NodeType

logger = logging.getLogger("hfpapers.graph.viz.geo_map")

# ── Default output paths ──────────────────────────────────
DEFAULT_FOLIUM = "~/data/kg/community_map.html"
DEFAULT_STATIC = "~/data/kg/community_map.pdf"

# ── Color palette (tab10, accessible) ─────────────────────
_TAB10 = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]


def _community_color(cid: int) -> str:
    """Return a deterministic color for a community id."""
    return _TAB10[cid % len(_TAB10)]


def _lighten_color(hex_color: str, factor: float = 0.4) -> str:
    """Lighten a hex color by blending with white."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def _compute_communities(G: "nx.Graph") -> dict[str, int]:  # noqa: N802
    """Run Louvain detection on paper citation subgraph.

    Returns dict mapping PAPER node ID → community_id.
    Uses Leiden as preferred community detection algorithm.
    Falls back to label propagation if scipy is missing.
    """
    # Build citation subgraph from PAPER nodes with CITES edges
    papers = {n for n, d in G.nodes(data=True)
              if getattr(d.get("type"), "name", d.get("type")) == "PAPER"}
    H = G.subgraph(papers).copy()

    if H.number_of_nodes() < 2:
        return {}

    # Ensure undirected for community detection
    if G.is_directed():
        H = H.to_undirected()

    try:
        from networkx.algorithms.community import louvain_communities
        communities = list(louvain_communities(H, seed=42))
        logger.info("Louvain: %d communities", len(communities))
    except (ImportError, AttributeError):
        try:
            from networkx.algorithms.community import greedy_modularity_communities
            communities = list(greedy_modularity_communities(H))
            logger.info("Greedy modularity: %d communities", len(communities))
        except (ImportError, AttributeError):
            from networkx.algorithms.community import label_propagation_communities
            communities = list(label_propagation_communities(H))
            logger.info("Label Propagation: %d communities", len(communities))

    paper_community: dict[str, int] = {}
    for cid, members in enumerate(communities):
        for node in members:
            paper_community[node] = cid
    return paper_community


def aggregate_institution_communities(
    G: "nx.Graph",  # noqa: N802
    min_papers: int = 1,
    use_city_fallback: bool = True,
) -> dict:
    """Aggregate community composition per geographic location.

    Returns a dict keyed by location node ID with structure::

        {
            "inst:ustc": {
                "label": "University of Science and Technology of China",
                "lat": 31.8195, "lng": 117.2497,
                "type": "INSTITUTION",
                "total_papers": 45,
                "communities": {0: 20, 1: 15, 3: 10},  # cid → paper_count
                "dominant": 0,
                "color": "#1f77b4",
                "persons": ["Chen, Xiangdong", ...],
            },
            ...
        }

    Args:
        G: NetworkX knowledge graph.
        min_papers: Minimum papers to include a location (filter noise).
        use_city_fallback: If True, aggregate INSTITUTION-less papers to CITY nodes.

    Returns:
        Location → community composition mapping.
    """
    paper_comm = _compute_communities(G)

    # Build person → [paper_ids]
    person_papers: dict[str, set[str]] = {}
    for u, v, d in G.edges(data=True):
        etype = d.get("type") if isinstance(d, dict) else None
        if etype is None:
            continue
        et_name = getattr(etype, "name", etype) if etype else ""
        ut = getattr(G.nodes[u].get("type"), "name", G.nodes[u].get("type"))
        vt = getattr(G.nodes[v].get("type"), "name", G.nodes[v].get("type"))

        if et_name == getattr(EdgeType.AUTHOR_OF, "name", "AUTHOR_OF"):
            person = u if ut == "PERSON" else v
            paper = v if ut == "PERSON" else u
            person_papers.setdefault(person, set()).add(paper)

    # Build location → community counts
    loc_comm: dict[str, dict] = {}

    # Process INSTITUTION nodes
    inst_nodes = [
        (n, d) for n, d in G.nodes(data=True)
        if getattr(d.get("type"), "name", d.get("type")) == "INSTITUTION"
    ]

    for nid, data in inst_nodes:
        lat, lng = data.get("lat"), data.get("lng")
        if not lat or not lng:
            continue
        label = data.get("label", nid)[:80]
        persons_at_inst = _affiliated_persons(G, nid)

        comm_counts: dict[int, int] = {}
        for p in persons_at_inst:
            for paper in person_papers.get(p, set()):
                cid = paper_comm.get(paper)
                if cid is not None:
                    comm_counts[cid] = comm_counts.get(cid, 0) + 1

        total = sum(comm_counts.values())
        if total < min_papers:
            continue

        dominant = max(comm_counts, key=comm_counts.get)
        loc_comm[nid] = {
            "label": label,
            "lat": float(lat),
            "lng": float(lng),
            "type": "INSTITUTION",
            "total_papers": total,
            "communities": comm_counts,
            "dominant": dominant,
            "color": _community_color(dominant),
            "persons": list(persons_at_inst),
        }

    # CITY/COUNTRY fallback: aggregate papers without institution
    if use_city_fallback and not loc_comm:
        city_nodes = [
            (n, d) for n, d in G.nodes(data=True)
            if getattr(d.get("type"), "name", d.get("type")) in ("CITY", "COUNTRY")
        ]
        for nid, data in city_nodes:
            lat, lng = data.get("lat"), data.get("lng")
            if not lat or not lng:
                continue
            label = data.get("label", nid)[:80]

            # Find affiliated institutions → persons → papers
            insts = list(G.neighbors(nid))
            comm_counts = {}
            all_persons = set()
            for inst in insts:
                for p in _affiliated_persons(G, inst):
                    all_persons.add(p)
                    for paper in person_papers.get(p, set()):
                        cid = paper_comm.get(paper)
                        if cid is not None:
                            comm_counts[cid] = comm_counts.get(cid, 0) + 1

            total = sum(comm_counts.values())
            if total < min_papers:
                continue
            dominant = max(comm_counts, key=comm_counts.get)
            ntype = getattr(data.get("type"), "name", "CITY")
            loc_comm[nid] = {
                "label": label,
                "lat": float(lat),
                "lng": float(lng),
                "type": ntype,
                "total_papers": total,
                "communities": comm_counts,
                "dominant": dominant,
                "color": _community_color(dominant),
                "persons": list(all_persons),
            }

    logger.info("Aggregated %d locations with community data", len(loc_comm))
    return loc_comm


def _affiliated_persons(G: "nx.Graph", inst_id: str) -> list[str]:  # noqa: N802
    """Return list of person node IDs affiliated with an institution."""
    persons = []
    et_aff = getattr(EdgeType.AFFILIATED_WITH, "name", "AFFILIATED_WITH")
    for neighbor in G.neighbors(inst_id):
        ed = G.get_edge_data(inst_id, neighbor)
        if ed is None:
            continue
        if isinstance(ed, dict):
            etype_val = ed.get("type")
        else:
            etype_val = ed
        etype_name = getattr(etype_val, "name", etype_val) if etype_val else ""
        if etype_name == et_aff:
            nd = G.nodes.get(neighbor, {})
            nt = getattr(nd.get("type"), "name", nd.get("type"))
            if nt == "PERSON":
                persons.append(neighbor)
    return persons


def render_community_folium(
    G: "nx.Graph",  # noqa: N802
    loc_comm: Optional[dict] = None,
    output: str = DEFAULT_FOLIUM,
    map_center: Optional[list[float]] = None,
    zoom_start: int = 3,
    show_edges: bool = True,
    edge_alpha: float = 0.15,
    min_papers: int = 1,
) -> str:
    """Render community-colored institutions on an interactive folium map.

    Args:
        G: NetworkX knowledge graph.
        loc_comm: Pre-computed location→community mapping (from
            :func:`aggregate_institution_communities`). Auto-computed if None.
        output: Output HTML path.
        map_center: [lat, lng] map center. Defaults to China centroid.
        zoom_start: Initial zoom level.
        show_edges: Draw geodesic collaboration edges between locations.
        edge_alpha: Edge line opacity (0-1).
        min_papers: Minimum papers to show a location.

    Returns:
        Path to generated HTML file.
    """
    import folium
    from folium.plugins import MarkerCluster

    if loc_comm is None:
        loc_comm = aggregate_institution_communities(G, min_papers=min_papers)

    if not loc_comm:
        logger.warning("No location data to render")
        return ""

    center = map_center or [35.0, 105.0]
    m = folium.Map(
        location=center,
        zoom_start=zoom_start,
        tiles="CartoDB Positron",
        control_scale=True,
    )

    # ── Legend (HTML overlay) ─────────────────────────────
    _add_legend(m, loc_comm)

    # ── Edges (geodesic polylines) ────────────────────────
    if show_edges and len(loc_comm) > 1:
        locs = list(loc_comm.values())
        for i in range(len(locs)):
            for j in range(i + 1, len(locs)):
                a, b = locs[i], locs[j]
                folium.PolyLine(
                    locations=[[a["lat"], a["lng"]], [b["lat"], b["lng"]]],
                    color="#888",
                    weight=0.5,
                    opacity=edge_alpha,
                    dash_array="4, 8",
                ).add_to(m)

    # ── Nodes (MarkerCluster) ────────────────────────────
    cluster = MarkerCluster(
        name="Communities",
        options={"spiderfyOnMaxZoom": True, "showCoverageOnHover": False},
    ).add_to(m)

    for nid, info in loc_comm.items():
        color = info["color"]
        size = max(8, min(30, 8 + info["total_papers"] * 2))

        # Build popup HTML
        comms_sorted = sorted(info["communities"].items(), key=lambda x: -x[1])
        comm_html = "<br>".join(
            f'<span style="color:{_community_color(cid)}">■</span> '
            f"Community {cid}: {count} papers"
            for cid, count in comms_sorted[:10]
        )
        if len(info["communities"]) > 10:
            comm_html += f"<br>... +{len(info['communities']) - 10} more"

        persons_str = ", ".join(
            G.nodes.get(p, {}).get("label", p)[:20] for p in info["persons"][:8]
        )
        if len(info["persons"]) > 8:
            persons_str += " ..."

        popup_html = (
            f"<b>{info['label']}</b><br>"
            f"<small>{info['type']} | {info['total_papers']} papers</small><hr>"
            f"<b>Communities:</b><br>{comm_html}"
            f"<hr><small><b>Persons:</b><br>{persons_str}</small>"
        )

        folium.CircleMarker(
            location=[info["lat"], info["lng"]],
            radius=size / 2,
            color=color,
            fill=True,
            fill_color=_lighten_color(color, 0.5),
            fill_opacity=0.8,
            popup=folium.Popup(popup_html, max_width=350),
            tooltip=f"{info['label']} ({info['total_papers']} papers)",
        ).add_to(cluster)

    folium.LayerControl().add_to(m)

    path = Path(output or DEFAULT_FOLIUM).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(path))
    logger.info("Community map saved: %d locations → %s", len(loc_comm), path)
    return str(path)


def _add_legend(m, loc_comm: dict):
    """Add a community color legend to the map."""
    import folium
    # Collect unique communities
    seen = {}
    for info in loc_comm.values():
        for cid, count in info["communities"].items():
            if cid not in seen:
                seen[cid] = {"count": 0, "color": _community_color(cid)}
            seen[cid]["count"] += count

    sorted_cids = sorted(seen.keys())[:15]

    items_html = ""
    for cid in sorted_cids:
        c = seen[cid]["color"]
        cnt = seen[cid]["count"]
        items_html += f'<span style="color:{c}">■</span> C{cid}: {cnt}<br>'

    legend_html = f"""
    <div style="
        position: fixed;
        bottom: 20px; right: 20px;
        background: white;
        padding: 10px 14px;
        border-radius: 6px;
        box-shadow: 0 0 8px rgba(0,0,0,0.2);
        font-size: 12px;
        z-index: 9999;
        max-height: 300px;
        overflow-y: auto;
    ">
    <b>Communities</b><br>
    {items_html}
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))


def render_community_static(
    G: "nx.Graph",  # noqa: N802
    loc_comm: Optional[dict] = None,
    output: str = DEFAULT_STATIC,
    projection: str = "robinson",
    figsize: tuple = (14, 8),
    min_papers: int = 1,
    show_edges: bool = True,
) -> str:
    """Render a publication-quality static map using cartopy.

    Requires ``cartopy`` and ``matplotlib``.

    Args:
        G: NetworkX knowledge graph.
        loc_comm: Pre-computed location→community mapping.
        output: Output path (.pdf or .png).
        projection: Map projection — "robinson", "mollweide", "platecarree".
        figsize: Figure size in inches.
        min_papers: Minimum papers to show a location.
        show_edges: Draw geodesic edges between locations.

    Returns:
        Path to generated file, or empty string if cartopy not available.
    """
    try:
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        # Apply SciencePlots style for publication-quality appearance
        try:
            import scienceplots
            plt.style.use(["science", "nature"])
            # Disable LaTeX text rendering — TinyTeX may lack packages
            plt.rcParams["text.usetex"] = False
            logger.info("SciencePlots style applied (usetex=False)")
        except Exception:
            pass
    except ImportError:
        logger.warning("cartopy not installed. Install with: pip install cartopy")
        return ""

    if loc_comm is None:
        loc_comm = aggregate_institution_communities(G, min_papers=min_papers)

    if not loc_comm:
        logger.warning("No location data to render")
        return ""

    # Projection selection
    proj_map = {
        "robinson": ccrs.Robinson(),
        "mollweide": ccrs.Mollweide(),
        "platecarree": ccrs.PlateCarree(),
        "orthographic": ccrs.Orthographic(central_longitude=105, central_latitude=35),
        "china": ccrs.LambertConformal(central_longitude=105, central_latitude=36,
                                        standard_parallels=(30, 42)),
    }
    proj = proj_map.get(projection, ccrs.Robinson())

    fig = plt.figure(figsize=figsize)
    ax = plt.axes(projection=proj)
    if projection == "china":
        ax.set_extent([70, 140, 15, 55], crs=ccrs.PlateCarree())
    else:
        ax.set_global()

    # Coastlines and borders
    ax.add_feature(cfeature.LAND, facecolor="#f0f0f0", edgecolor="#ddd", linewidth=0.3)
    ax.add_feature(cfeature.OCEAN, facecolor="#e8f4f8")
    ax.add_feature(cfeature.COASTLINE, edgecolor="#bbb", linewidth=0.5)
    ax.add_feature(cfeature.BORDERS, edgecolor="#ccc", linewidth=0.3, linestyle=":")

    # Gridlines
    gl = ax.gridlines(draw_labels=False, linewidth=0.5, color="#ddd", alpha=0.5)

    # ── Edges ────────────────────────────────────────────
    if show_edges and len(loc_comm) > 1:
        locs = list(loc_comm.values())
        for i in range(len(locs)):
            for j in range(i + 1, len(locs)):
                a, b = locs[i], locs[j]
                ax.plot(
                    [a["lng"], b["lng"]],
                    [a["lat"], b["lat"]],
                    transform=ccrs.Geodetic(),
                    color="#999",
                    linewidth=0.8,
                    alpha=0.45,
                    linestyle="--",
                )

    # ── Nodes ────────────────────────────────────────────
    for nid, info in loc_comm.items():
        size = max(20, min(200, 20 + info["total_papers"] * 8))
        color = info["color"]

        ax.scatter(
            info["lng"], info["lat"],
            transform=ccrs.PlateCarree(),
            c=color,
            s=size,
            edgecolors="white",
            linewidths=0.5,
            zorder=5,
            label=info["label"][:30],
        )

    # ── Legend ───────────────────────────────────────────
    seen = {}
    for info in loc_comm.values():
        for cid in info["communities"]:
            seen[cid] = _community_color(cid)
    sorted_cids = sorted(seen.keys())[:10]
    legend_elements = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=seen[cid],
                   markersize=8, label=f"C{cid}")
        for cid in sorted_cids
    ]
    ax.legend(
        handles=legend_elements,
        loc="lower left",
        frameon=True,
        fontsize=8,
        title="Communities",
    )

    path = Path(output or DEFAULT_STATIC).expanduser()
    if not output and projection != "robinson":
        # Use projection-specific filename
        path = path.with_stem(f"community_map_{projection}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(path), dpi=300, bbox_inches="tight")
    plt.close(fig)
    logger.info("Community static map saved: %d locations → %s", len(loc_comm), path)
    return str(path)


def enrich_institutions_from_arxiv(
    G: "nx.Graph",  # noqa: N802
    batch_size: int = 50,
    max_papers: int = 200,
) -> dict[str, int]:
    """Scrape arXiv API for paper affiliations and add INSTITUTION nodes.

    Iterates over PAPER nodes with arXiv IDs, fetches their arXiv metadata
    (which includes author affiliations), geocodes unique institutions, and
    adds INSTITUTION / CITY / COUNTRY nodes + AFFILIATED_WITH / LOCATED_IN edges.

    Args:
        G: NetworkX knowledge graph (mutated in-place).
        batch_size: Papers to process before saving cache.
        max_papers: Max papers to process (0 = unlimited).

    Returns:
        Stats dict.
    """
    import time
    import urllib.request
    import xml.etree.ElementTree as ET

    from hfpapers.graph.schema import EdgeType, NodeType, node_id
    from hfpapers.graph.sources.institutions import (
        GeoCache,
        geocode_institutions,
        institution_abbrev,
    )

    # Collect papers with arXiv IDs
    papers = []
    for n, d in G.nodes(data=True):
        t = getattr(d.get("type"), "name", d.get("type"))
        if t != "PAPER":
            continue
        aid = d.get("arxiv_id", "")
        if not aid or aid == "paper:" or not aid.startswith(("20", "19", "18", "17", "16", "15", "14")):
            continue
        papers.append((n, aid))

    if max_papers > 0:
        papers = papers[:max_papers]

    logger.info("arXiv enrichment: %d papers to process", len(papers))

    # Fetch arXiv metadata in batches
    author_institutions: dict[str, set[str]] = {}  # person_label → institution set
    geo_cache = GeoCache()

    for i in range(0, len(papers), 50):
        batch = papers[i:i + 50]
        ids = ",".join(aid for _, aid in batch)
        url = f"http://export.arxiv.org/api/query?id_list={ids}&max_results=50"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hfpclawer/0.12.1"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                xml_data = resp.read().decode("utf-8")
        except Exception as e:
            logger.warning("arXiv API batch %d failed: %s", i, e)
            time.sleep(3)
            continue

        ns = {"a": "http://www.w3.org/2005/Atom",
              "arxiv": "http://arxiv.org/schemas/atom"}
        root = ET.fromstring(xml_data)
        for entry in root.findall("a:entry", ns):
            title_el = entry.find("a:title", ns)
            if title_el is None or not title_el.text:
                continue
            title = title_el.text.strip().replace("\n", " ")

            # Find matching paper node
            matched = None
            for nid, aid in batch:
                dn = G.nodes[nid]
                if dn.get("title", "").strip().lower() == title.lower():
                    matched = nid
                    break
            if not matched:
                continue

            # Extract authors and their affiliations
            for author_el in entry.findall("a:author", ns):
                name_el = author_el.find("a:name", ns)
                if name_el is None or not name_el.text:
                    continue
                author_name = name_el.text.strip()

                # Get affiliations
                affils = []
                for affil_el in author_el.findall("arxiv:affiliation", ns):
                    if affil_el.text and affil_el.text.strip():
                        affils.append(affil_el.text.strip())

                if not affils:
                    continue

                for affil in affils:
                    author_institutions.setdefault(author_name, set()).add(affil)

        time.sleep(0.5)  # Be polite to arXiv API

    logger.info("Found %d authors with affiliations", len(author_institutions))

    if not author_institutions:
        logger.warning("No affiliations found from arXiv API")
        return {"institutions": 0, "affiliations": 0}

    # Flatten unique institution names
    all_inst_names = set()
    for insts in author_institutions.values():
        all_inst_names.update(insts)
    all_inst_names = {n for n in all_inst_names if n}  # remove empty

    logger.info("Unique institution names: %d", len(all_inst_names))

    # Geocode via existing pipeline
    geo_data = geocode_institutions(list(all_inst_names), cache=geo_cache)
    logger.info("Geocoded %d institutions", len(geo_data))

    # Add INSTITUTION/CITY/COUNTRY nodes to graph
    n_inst = 0
    n_city = 0
    n_country = 0
    n_affil = 0
    n_located = 0

    for inst_name, info in geo_data.items():
        canonical = info.get("canonical", inst_name)[:80]
        city = info.get("city", "")
        country = info.get("country", "")
        lat = info.get("lat")
        lng = info.get("lng")
        geo_src = info.get("source", "arxiv")

        if not lat or not lng:
            continue

        # Create INSTITUTION node
        inst_id = node_id(NodeType.INSTITUTION, canonical)
        if inst_id not in G:
            G.add_node(inst_id, type=NodeType.INSTITUTION, label=canonical,
                       abbrev=institution_abbrev(canonical),
                       lat=lat, lng=lng, city=city, country=country,
                       geo_source=geo_src)
            n_inst += 1

        # CITY node
        if city:
            city_id = node_id(NodeType.CITY, city)
            if city_id not in G:
                G.add_node(city_id, type=NodeType.CITY, label=city,
                           lat=lat, lng=lng, country=country)
                n_city += 1
            G.add_edge(inst_id, city_id, type=EdgeType.LOCATED_IN)
            n_located += 1

        # COUNTRY node
        if country:
            ctry_id = node_id(NodeType.COUNTRY, country)
            if ctry_id not in G:
                G.add_node(ctry_id, type=NodeType.COUNTRY, label=country)
                n_country += 1
            if city:
                G.add_edge(node_id(NodeType.CITY, city), ctry_id,
                           type=EdgeType.LOCATED_IN)
                n_located += 1

        # Connect persons to this institution
        for author_name, insts in author_institutions.items():
            if inst_name not in insts:
                continue
            # Find the person node in the graph
            for nid, nd in G.nodes(data=True):
                nt = getattr(nd.get("type"), "name", nd.get("type"))
                if nt != "PERSON":
                    continue
                label = nd.get("label", "")
                if author_name.lower() in label.lower() or label.lower() in author_name.lower():
                    G.add_edge(nid, inst_id, type=EdgeType.AFFILIATED_WITH)
                    n_affil += 1
                    break

    stats = {
        "institutions": n_inst,
        "cities": n_city,
        "countries": n_country,
        "affiliations": n_affil,
        "located_in": n_located,
    }
    logger.info("arXiv enrichment done: %s", stats)
    return stats
