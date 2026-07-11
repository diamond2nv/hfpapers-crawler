#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hfpclawer graph CLI subcommand.

Registered as ``hfpclawer graph {build, stats, export, person, community, path}``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import networkx as nx
from rich.console import Console

console = Console()
logger = logging.getLogger("hfpclawer.graph")


def cmd_build(limit: int = 200, force: bool = False) -> None:
    """Build the knowledge graph from Zotero + wiki sources."""
    from hfpapers.graph import GraphBuilder
    from hfpclawer.zotero import ZoteroClient

    # Configure spaCy if available (for innovation topic extraction)
    try:
        from hfpapers.nlp import configure as nlp_configure
        nlp_configure("en_core_web_md")
    except Exception:
        pass

    console.print(f"[dim]Building graph (limit={limit}, force={force})...[/dim]")

    zc = ZoteroClient()
    builder = GraphBuilder()

    try:
        G = builder.build(client=zc, limit=limit, force=force)
        console.print(f"[green]✅ Graph built: {G.number_of_nodes()} nodes, "
                      f"{G.number_of_edges()} edges[/green]")
        builder.stats(G)
    except Exception as e:
        console.print(f"[red]❌ Build failed: {e}[/red]")
        logger.exception("Graph build failed")
        raise SystemExit(1) from e


def cmd_stats(detail: bool = False) -> None:
    """Show graph statistics from the last build."""
    from hfpapers.graph import GraphBuilder

    G = GraphBuilder.load()
    if G is None:
        console.print("[yellow]⚠️  No graph built yet. Run 'hfpclawer graph build' first.[/yellow]")
        return

    builder = GraphBuilder()
    builder.G = G
    builder.stats(G)


def cmd_export(
    fmt: str = "jsonl",
    output: str = "",
    limit: int = 200,
) -> None:
    """Export the graph for cross-repo consumption.

    Args:
        fmt: Export format: ``jsonl`` (for hedge), ``graphml`` (for Gephi).
        output: Output file path.
        limit: If building on-the-fly, max Zotero items.
    """
    from hfpapers.graph import GraphBuilder

    G = GraphBuilder.load()
    if G is None:
        console.print("[yellow]⚠️  No saved graph. Building on-the-fly...[/yellow]")
        try:
            from hfpclawer.zotero import ZoteroClient
            zc = ZoteroClient()
            builder = GraphBuilder()
            G = builder.build(client=zc, limit=limit)
        except Exception as e:
            console.print(f"[red]❌ Build failed: {e}[/red]")
            raise SystemExit(1) from e

    builder = GraphBuilder()
    output_path = output or (
        os.path.expanduser("~/data/kg/subgraph_a.jsonl") if fmt == "jsonl"
        else os.path.expanduser("~/data/kg/subgraph_a.graphml")
    )

    if fmt == "jsonl":
        path = builder.export_jsonl(output_path, G)
    elif fmt == "graphml":
        path = builder.export_graphml(output_path, G)
    else:
        console.print(f"[red]❌ Unknown format: {fmt}. Use 'jsonl' or 'graphml'.[/red]")
        return

    console.print(f"[green]✅ Exported → {path}[/green]")
    console.print(f"   {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")


def _load_builder() -> tuple:
    """Load cached graph and return (GraphBuilder, G).

    Returns:
        (builder, G) tuple. Prints error and exits if no cache.
    """
    from hfpapers.graph import GraphBuilder

    G = GraphBuilder.load()
    if G is None:
        console.print("[yellow]⚠️  No graph cache. Run 'hfpclawer graph build' first.[/yellow]")
        raise SystemExit(1)
    builder = GraphBuilder()
    builder.G = G
    return builder, G


def cmd_person(person_id: str, depth: int = 1, top_n: int = 20) -> None:
    """Show person node details and ego network.

    Accepts:
    - Node ID (``person:guo-gua``)
    - Short ID (``guo-gua``)
    - English name (``Guo Guang-Can``, ``Chen, Xiangdong``)
    - Chinese name (``郭光灿``, ``Guo Guang-Can``)
    - Partial match (``Guo``)

    Args:
        person_id: Person identifier.
        depth: Ego network radius.
        top_n: Max ego network nodes to list.
    """
    from hfpapers.graph.schema import person_node_id as _pid

    builder, G = _load_builder()
    nid = _resolve_person_id(G, person_id)
    if nid is None:
        # Fuzzy search: find by substring in label or node ID
        fuzzy = _fuzzy_person_search(G, person_id)
        if fuzzy:
            console.print(f"[yellow]⚠️  No exact match for '{person_id}'.[/yellow]")
            console.print(f"[dim]Did you mean:[/dim]")
            for match_id, match_label, score in fuzzy[:5]:
                console.print(f"   [dim]• {match_label:35s} ({match_id}) — match: {score:.0%}[/dim]")
        else:
            console.print(f"[red]❌ No person found matching '{person_id}'.[/red]")
        raise SystemExit(1)

    data = G.nodes[nid]
    console.print(f"\n[bold cyan]👤 {data.get('label', nid)}[/bold cyan]")
    console.print(f"   ID: {nid}")
    for k, v in sorted(data.items()):
        if k in ("label", "type", "color", "size", "icon"):
            continue
        console.print(f"   [dim]{k}:[/dim] {v}")

    # Ego network
    ego = builder.person_ego(nid, depth=depth)
    if ego is None:
        return

    console.print(f"\n[bold]🔗 Ego Network (depth={depth})[/bold]")
    console.print(f"   Nodes: {ego.number_of_nodes()}, Edges: {ego.number_of_edges()}")

    # List neighbours
    neighbors = list(ego.neighbors(nid))[:top_n]
    if neighbors:
        console.print(f"\n[bold]Neighbours (top {len(neighbors)}):[/bold]")
        for nb in neighbors:
            nb_data = G.nodes[nb]
            nt = nb_data.get("type", "")
            if hasattr(nt, "name"):
                nt = nt.name
            console.print(f"   • {nb_data.get('label', nb)[:55]}  [dim]({nt}: {nb})[/dim]")


def _resolve_person_id(G, raw: str) -> str | None:
    """Resolve a person identifier to a node ID.

    Tries (in order):
    1. Exact node ID (```person:xxx```)
    2. ```person:{raw}``` (short ID)
    3. Parse full name with ```person_node_id``` logic
    4. ``Last, First`` format → direct person_node_id
    """
    from hfpapers.graph.schema import person_node_id as _pid

    # Already a node ID
    if raw.startswith("person:") and raw in G:
        return raw

    # Try as short ID
    nid = f"person:{raw}"
    if nid in G:
        return nid

    # Parse as full name
    raw_stripped = raw.strip()

    # "Last, First" format
    if "," in raw_stripped:
        parts = raw_stripped.split(",", 1)
        last = parts[0].strip()
        first = parts[1].strip()
        nid = _pid(last, first)
        if nid in G:
            return nid
        # Try slugified version
        nid = f"person:{_slugify(last)}-{_slugify(first[:3])}"
        if nid in G:
            return nid
        # Try reverse (Chinese convention)
        nid = _pid(first, last)
        if nid in G:
            return nid

    # "First Last" or "Last First" (space-separated)
    elif " " in raw_stripped:
        parts = raw_stripped.rsplit(" ", 1)
        last = parts[1].strip()  # Last word as surname
        first = parts[0].strip()

        # Try (last, first)
        nid = _pid(last, first)
        if nid in G:
            return nid

        # Try (first, last) — Chinese name order
        nid = _pid(first, last)
        if nid in G:
            return nid

        # Try slugified shortcut
        nid = f"person:{_slugify(last)}-{_slugify(first[:3])}"
        if nid in G:
            return nid

    return None


def _slugify(s: str) -> str:
    """Simple slugify matching schema._slugify."""
    import re
    s = s.lower().strip()
    s = re.sub(r"[^\w\s\u4e00-\u9fff]", "-", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-") or "unknown"


def _fuzzy_person_search(G, query: str, top_n: int = 5) -> list[tuple[str, str, float]]:
    """Fuzzy search persons by label or node ID.

    Returns:
        List of (node_id, label, similarity_score) sorted by score descending.
    """
    from difflib import SequenceMatcher

    q = query.lower().strip()
    results = []
    seen: set[str] = set()
    for nid, data in G.nodes(data=True):
        if not nid.startswith("person:"):
            continue
        label = data.get("label", nid)
        label_lower = label.lower()

        # Exact word match
        words = q.split()
        word_matches = sum(1 for w in words if w in label_lower or w in nid.lower())
        if word_matches > 0:
            score = word_matches / max(len(words), 1) * 0.8 + 0.2
        else:
            # Sequence matcher fallback
            score = max(
                SequenceMatcher(None, q, nid.lower()).ratio(),
                SequenceMatcher(None, q, label_lower).ratio(),
            )
            if score < 0.3:
                continue

        key = (nid, label)
        if key not in seen:
            seen.add(key)
            results.append((nid, label, score))

    results.sort(key=lambda x: -x[2])
    return results[:top_n]


def cmd_community(min_size: str = "", top_n: int = 20) -> None:
    """List detected communities in the graph.

    Args:
        min_size: Minimum community size filter (int or empty for all).
        top_n: Top N communities to show.
    """
    builder, G = _load_builder()

    communities = builder.communities()
    min_sz = int(min_size) if min_size.strip() else 0

    filtered = [c for c in communities if len(c) >= min_sz][:top_n]
    console.print(f"\n[bold cyan]🏘️  Communities ({len(filtered)} shown / {len(communities)} total)[/bold cyan]")

    for i, community in enumerate(filtered, 1):
        # Get top labels from each community
        labels = []
        for nid in list(community)[:5]:
            data = G.nodes[nid]
            labels.append(data.get("label", nid)[:40])
        more = len(community) - len(labels)
        label_str = ", ".join(labels)
        if more > 0:
            label_str += f" [dim]+{more} more[/dim]"
        console.print(f"   {i:2d}. [{len(community):3d} nodes] {label_str}")


def cmd_path(source: str, target: str) -> None:
    """Find shortest path between two nodes.

    Args:
        source: Source node ID.
        target: Target node ID.
    """
    builder, G = _load_builder()

    # Normalize IDs
    def _norm(nid: str) -> str:
        if ":" not in nid:
            # Try person
            p = f"person:{nid}"
            if p in G:
                return p
        return nid

    src = _norm(source)
    tgt = _norm(target)

    if src not in G:
        console.print(f"[red]❌ Source '{source}' not found in graph.[/red]")
        raise SystemExit(1)
    if tgt not in G:
        console.print(f"[red]❌ Target '{target}' not found in graph.[/red]")
        raise SystemExit(1)

    try:
        path = builder.shortest_path(src, tgt)
        console.print("\n[bold cyan]🛤️  Shortest Path[/bold cyan]")
        console.print(f"   {len(path)-1} hops")
        for i, nid in enumerate(path):
            data = G.nodes[nid]
            nt = data.get("type", "")
            if hasattr(nt, "name"):
                nt = nt.name
            label = data.get("label", nid)[:50]
            prefix = "→" if i > 0 else " "
            console.print(f"   {prefix} [{nt}] {label}  [dim]({nid})[/dim]")
    except ValueError as e:
        console.print(f"[red]❌ {e}[/red]")
        raise SystemExit(1) from e
    except nx.NetworkXNoPath:
        console.print(f"[red]❌ No path between '{source}' and '{target}'[/red]")
        raise SystemExit(1)


# ── Geo commands ────────────────────────────────────────────────


def cmd_geo_stats() -> None:
    """Show geo enrichment statistics from the last build."""
    builder, G = _load_builder()

    # Count geo nodes
    n_inst = sum(1 for _, d in G.nodes(data=True)
                 if d.get("type") and getattr(d["type"], "name", d["type"]) == "INSTITUTION")
    n_city = sum(1 for _, d in G.nodes(data=True)
                 if d.get("type") and getattr(d["type"], "name", d["type"]) == "CITY")
    n_country = sum(1 for _, d in G.nodes(data=True)
                    if d.get("type") and getattr(d["type"], "name", d["type"]) == "COUNTRY")
    n_affil = sum(1 for _, _, d in G.edges(data=True)
                  if d.get("type") and getattr(d["type"], "name", d["type"]) == "AFFILIATED_WITH")

    # Count by country
    countries: dict[str, int] = {}
    for _, d in G.nodes(data=True):
        if d.get("type") and getattr(d["type"], "name", d["type"]) == "INSTITUTION":
            country = d.get("country", d.get("label", "")[-20:])
            countries[country] = countries.get(country, 0) + 1

    console.print("\n[bold cyan]🌍 Geo Enrichment Statistics[/bold cyan]")
    console.print(f"   🏛 Institutions: {n_inst}")
    console.print(f"   🏙 Cities:       {n_city}")
    console.print(f"   🌍 Countries:    {n_country}")
    console.print(f"   🔗 Affiliations: {n_affil}")
    if countries:
        console.print(f"\n[bold]By Country:[/bold]")
        for country, count in sorted(countries.items(), key=lambda x: -x[1]):
            console.print(f"   • {country}: {count}")


def cmd_geo_institutions(detail: bool = False) -> None:
    """List all institutions with location data."""
    _, G = _load_builder()

    institutions = []
    for nid, data in G.nodes(data=True):
        nt = data.get("type")
        if not nt or getattr(nt, "name", nt) != "INSTITUTION":
            continue
        institutions.append({
            "id": nid,
            "label": data.get("label", nid),
            "lat": data.get("lat", ""),
            "lng": data.get("lng", ""),
            "geo_source": data.get("geo_source", ""),
        })

    if not institutions:
        console.print("[yellow]⚠️  No institutions in graph. Rebuild with 'hfpclawer graph build'.[/yellow]")
        return

    console.print(f"\n[bold cyan]🏛 Institutions ({len(institutions)})[/bold cyan]")
    for inst in sorted(institutions, key=lambda x: x["label"]):
        lat = inst["lat"]
        lng = inst["lng"]
        src = inst["geo_source"]
        if lat and lng and float(lat) != 0.0:
            coord = f"{float(lat):.3f}, {float(lng):.3f}"
            console.print(f"   • {inst['label'][:55]:55s} [{coord:20s}] [dim]{src}[/dim]")
        else:
            console.print(f"   • {inst['label'][:55]:55s} [dim]no coords[/dim]")


# ── Viz commands ────────────────────────────────────────────────


def cmd_map(output: str = "") -> None:
    """Generate an interactive institution map (folium HTML).

    Args:
        output: Output HTML path (default: ~/data/kg/institution_map.html).
    """
    _, G = _load_builder()

    n_inst = sum(1 for _, d in G.nodes(data=True)
                 if d.get("type") and getattr(d["type"], "name", d["type"]) == "INSTITUTION")
    if n_inst == 0:
        console.print("[yellow]⚠️  No institutions in graph. Rebuild with 'hfpclawer graph build' first.[/yellow]")
        return

    try:
        from hfpapers.graph.viz.folium import render_institution_map
        result = render_institution_map(G, output=output or "")
        console.print(f"[green]✅ Institution map → {result}[/green]")
        console.print(f"   {n_inst} institutions plotted")
    except Exception as e:
        console.print(f"[red]❌ Map generation failed: {e}[/red]")
        logger.exception("Map generation failed")
        raise SystemExit(1) from e


def cmd_community_map(
    output: str = "",
    show_edges: bool = True,
    min_papers: int = 1,
) -> None:
    """Generate an interactive community-overlaid institution map (folium).

    Color-codes institutions by dominant Louvain community.
    Draws geodesic collaboration edges between co-authoring locations.

    Args:
        output: Output HTML path (default: ~/data/kg/community_map.html).
        show_edges: Draw geodesic edges between locations.
        min_papers: Minimum papers to show a location.
    """
    _, G = _load_builder()

    n_geo = sum(1 for _, d in G.nodes(data=True)
                if d.get("lat") and d.get("lng"))
    if n_geo == 0:
        console.print("[yellow]⚠️  No geo data in graph. Rebuild with 'hfpclawer graph build' first.[/yellow]")
        return

    try:
        from hfpapers.graph.viz.geo_map import (
            aggregate_institution_communities,
            render_community_folium,
        )
        loc_comm = aggregate_institution_communities(G, min_papers=min_papers)
        if not loc_comm:
            console.print("[yellow]⚠️  No locations with community data found. Try --min-papers 1[/yellow]")
            return
        result = render_community_folium(
            G, loc_comm=loc_comm, output=output or "",
            show_edges=show_edges, min_papers=min_papers,
        )
        console.print(f"[green]✅ Community map → {result}[/green]")
        console.print(f"   {len(loc_comm)} locations plotted")
    except Exception as e:
        console.print(f"[red]❌ Community map failed: {e}[/red]")
        logger.exception("Community map failed")
        raise SystemExit(1) from e


def cmd_geo_globe(
    output: str = "",
    projection: str = "robinson",
    show_edges: bool = True,
    min_papers: int = 1,
) -> None:
    """Generate a publication-quality global map (cartopy).

    Nature-style Robinson projection with community-colored markers.

    Args:
        output: Output path (.pdf or .png, default: ~/data/kg/community_map.pdf).
        projection: Map projection (robinson, mollweide, platecarree, orthographic, china, yrd).
        show_edges: Draw geodesic edges between locations.
        min_papers: Minimum papers to show a location.
    """
    _, G = _load_builder()

    n_geo = sum(1 for _, d in G.nodes(data=True)
                if d.get("lat") and d.get("lng"))
    if n_geo == 0:
        console.print("[yellow]⚠️  No geo data in graph. Rebuild with 'hfpclawer graph build' first.[/yellow]")
        return

    try:
        from hfpapers.graph.viz.geo_map import (
            aggregate_institution_communities,
            render_community_static,
        )
        loc_comm = aggregate_institution_communities(G, min_papers=min_papers)
        if not loc_comm:
            console.print("[yellow]⚠️  No locations with community data found.[/yellow]")
            return
        result = render_community_static(
            G, loc_comm=loc_comm, output=output or "",
            projection=projection, show_edges=show_edges, min_papers=min_papers,
        )
        if result:
            console.print(f"[green]✅ Globe map → {result}[/green]")
            console.print(f"   {len(loc_comm)} locations, projection={projection}")
        else:
            console.print("[yellow]⚠️  cartopy not available. Install: pip install cartopy[/yellow]")
    except Exception as e:
        console.print(f"[red]❌ Globe map failed: {e}[/red]")
        logger.exception("Globe map failed")
        raise SystemExit(1) from e


# ── ORCID enrichment ──────────────────────────────────────────


def cmd_enrich_orcid(
    force: bool = False,
    limit: int = 0,
    save: bool = True,
) -> None:
    """Fetch employment/education affiliations from ORCID API and enrich graph.

    Scans the cached graph for PERSON nodes with ``orcid`` attributes,
    queries the ORCID public API, extracts institutions with addresses,
    and adds INSTITUTION / CITY / COUNTRY nodes + AFFILIATED_WITH edges.

    Args:
        force: Re-fetch all ORCIDs even if cached.
        limit: Max ORCIDs to fetch (0 = all).
        save: Save enriched graph back to cache.
    """
    from hfpapers.graph import GraphBuilder
    from hfpapers.graph.sources.orcid_enrich import (
        batch_fetch,
        enrich_graph_from_orcid,
        extract_orcids_from_graph,
    )

    _, G = _load_builder()

    # Step 1: Find ORCIDs in graph
    orcid_to_person = extract_orcids_from_graph(G)
    if not orcid_to_person:
        console.print("[yellow]⚠️  No PERSON nodes with ORCID found in graph.[/yellow]")
        return

    console.print(f"[blue]📡 Found {len(orcid_to_person)} ORCIDs in graph[/blue]")
    if limit and limit < len(orcid_to_person):
        orcid_to_person = dict(list(sorted(orcid_to_person.items()))[:limit])
        console.print(f"   (limited to first {limit})")

    # Step 2: Fetch from ORCID API
    console.print("[blue]📡 Fetching affiliations from ORCID API...[/blue]")
    results = batch_fetch(orcid_to_person, force=force)

    total_records = sum(len(v) for v in results.values())
    console.print(f"   → {total_records} affiliation records for {len(results)} ORCIDs")

    # Step 3: Enrich graph
    console.print("[blue]📡 Enriching graph with institution nodes...[/blue]")
    stats = enrich_graph_from_orcid(G, results, orcid_to_person)

    # Step 4: Save
    if save:
        builder = GraphBuilder()
        builder.G = G
        path = builder.save()
        console.print(f"[green]✅ ORCID enrichment done: +{stats['added_nodes']} nodes, "
                       f"+{stats['added_edges']} edges[/green]")
        console.print(f"   Graph saved → {path}")

        # Show geo stats
        n_geo = sum(1 for _, d in G.nodes(data=True)
                    if d.get("lat") and d.get("lng"))
        console.print(f"   Geo-enabled nodes: {n_geo}")
    else:
        console.print(f"[green]✅ ORCID enrichment done: +{stats['added_nodes']} nodes, "
                       f"+{stats['added_edges']} edges (not saved)[/green]")


def cmd_viz(style: str = "circos", output: str = "", source: str = "") -> None:
    """Generate graph visualization (Circos / spring).

    Args:
        style: 'circos' (default) for Circos plot, 'spring' for spring layout.
        output: Output image path (default: ~/data/kg/circos.png).
        source: Only include nodes with this source tag (e.g. 'coc', 'zotero').
    """
    _, G = _load_builder()

    # Filter by source tag if requested
    if source:
        source = source.lower()
        sub = nx.Graph()
        for nid, data in G.nodes(data=True):
            src = str(data.get("sources", "")).lower()
            if source in src:
                sub.add_node(nid, **dict(data))
        for u, v, data in G.edges(data=True):
            if u in sub and v in sub:
                sub.add_edge(u, v, **dict(data))
        G = sub
        console.print(f"[dim]Filtered to source='{source}': {G.number_of_nodes()} nodes, "
                      f"{G.number_of_edges()} edges[/dim]")
        if G.number_of_nodes() < 3:
            console.print("[yellow]⚠️  Too few nodes after filtering[/yellow]")
            return

    if style == "circos":
        try:
            from hfpapers.graph.viz.nxviz import render_circos
            result = render_circos(G, output=output if output else None)
            if result:
                console.print(f"[green]✅ Circos plot → {result}[/green]")
                console.print(f"   {G.number_of_nodes()} nodes in graph")
            else:
                console.print("[yellow]⚠️  Circos plot unavailable (nxviz/matplotlib not installed)[/yellow]")
        except Exception as e:
            console.print(f"[red]❌ Circos plot failed: {e}[/red]")
            logger.exception("Circos plot failed")
            raise SystemExit(1) from e
    elif style == "citation":
        try:
            from hfpapers.graph.viz.nxviz import render_citation_network
            result = render_citation_network(G, output=output if output else None)
            if result:
                console.print(f"[green]✅ Citation network → {result}[/green]")
                console.print(f"   {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
            else:
                console.print("[yellow]⚠️  Citation plot unavailable[/yellow]")
        except Exception as e:
            console.print(f"[red]❌ Citation plot failed: {e}[/red]")
            logger.exception("Citation plot failed")
    else:
        console.print(f"[red]❌ Unknown viz style: '{style}'. Use 'circos'.[/red]")


def cmd_ingest(source: str = "coc", path: str = "") -> None:
    """Import papers from a refs.jsonl file into the knowledge graph.

    Args:
        source: Short tag name (e.g. 'coc', 'gsnv').
        path: Path to refs.jsonl. Auto-detects coc-inverse-agent path if empty.
    """
    from hfpapers.graph import GraphBuilder

    # Auto-detect coc path
    if not path and source == "coc":
        coc_path = Path.home() / "Documents" / "Gitlab" / "forgejo-self-host" / \
                   "coc-inverse-agent" / "data" / "references" / "refs.jsonl"
        if coc_path.exists():
            path = str(coc_path)
        else:
            console.print("[red]❌ coc refs.jsonl not found at default path[/red]")
            raise SystemExit(1)

    path_obj = Path(path).expanduser()
    if not path_obj.exists():
        console.print(f"[red]❌ File not found: {path}[/red]")
        raise SystemExit(1)

    # Load or build graph
    cached = GraphBuilder.load()
    if cached is not None:
        G = cached
        console.print(f"[dim]Loaded cached graph ({G.number_of_nodes()} nodes, "
                      f"{G.number_of_edges()} edges)[/dim]")
    else:
        console.print("[yellow]No cached graph found. Run 'hfpclawer graph build' first.[/yellow]")
        return

    builder = GraphBuilder()
    builder.G = G
    result = builder.ingest_refs_jsonl(str(path_obj), tag=source)

    if result["papers_added"] == 0 and result["authors_added"] == 0:
        console.print("[yellow]No new papers to import (all already in graph)[/yellow]")
        return

    # Save updated graph
    builder.save()
    console.print(
        f"[green]✅ Imported {result['papers_added']} papers + "
        f"{result['authors_added']} authors from {source}[/green]"
    )
    console.print(f"   Graph now: {builder.G.number_of_nodes()} nodes, "
                  f"{builder.G.number_of_edges()} edges")


def cmd_ingest_citations(path: str = "") -> None:
    """Import citation edges from a coc-inverse-agent omc_graph.graphml.

    Args:
        path: Path to omc_graph.graphml. Auto-detects if empty.
    """
    from hfpapers.graph import GraphBuilder

    if not path:
        coc_path = Path.home() / "Documents" / "Gitlab" / "forgejo-self-host" / \
                   "coc-inverse-agent" / "data" / "references" / "omc_graph.graphml"
        if coc_path.exists():
            path = str(coc_path)

    path_obj = Path(path).expanduser()
    if not path_obj.exists():
        console.print(f"[red]❌ Citation GraphML not found: {path}[/red]")
        raise SystemExit(1)

    cached = GraphBuilder.load()
    if cached is None:
        console.print("[yellow]No cached graph found. Run 'hfpclawer graph build' first.[/yellow]")
        return

    builder = GraphBuilder()
    builder.G = cached
    result = builder.ingest_citation_graphml(str(path_obj))

    if result["edges_added"] == 0 and result["nodes_added"] == 0:
        console.print("[yellow]No new citation edges to import[/yellow]")
        return

    builder.save()
    console.print(
        f"[green]✅ Imported {result['edges_added']} citation edges + "
        f"{result['nodes_added']} new nodes[/green]"
    )
    console.print(f"   Graph now: {builder.G.number_of_nodes()} nodes, "
                  f"{builder.G.number_of_edges()} edges")


def cmd_expand_citations(
    max_depth: int = 2,
    max_seeds: int = 10,
    direction: str = "both",
) -> None:
    """Expand the knowledge graph via Semantic Scholar citation walking.

    Walks citation/reference edges outward from coc seed papers.

    Args:
        max_depth: Citation walk depth (1 = immediate neighbors).
        max_seeds: Max seed papers to expand from (0 = all).
        direction: 'references', 'citations', or 'both'.
    """
    from hfpapers.graph import GraphBuilder

    cached = GraphBuilder.load()
    if cached is None:
        console.print("[yellow]No cached graph found. Run 'hfpclawer graph build' first.[/yellow]")
        return

    builder = GraphBuilder()
    builder.G = cached

    console.print(f"[dim]Expanding citations (seeds={max_seeds}, depth={max_depth}, "
                  f"dir={direction})...[/dim]")

    try:
        result = builder.expand_citations(
            max_depth=max_depth,
            direction=direction,
            max_seeds=max_seeds,
        )
    except Exception as e:
        console.print(f"[red]❌ Citation expansion failed: {e}[/red]")
        logger.exception("Citation expansion failed")
        return

    if result["papers_found"] == 0 and result["edges_added"] == 0:
        console.print("[yellow]No new papers found via citation expansion[/yellow]")
        return

    builder.save()
    console.print(
        f"[green]✅ Citation expansion: {result['papers_found']} new papers, "
        f"{result['edges_added']} new edges[/green]"
    )
    console.print(f"   API calls: {result['api_calls']}, "
                  f"Skipped (already in graph): {result['skipped_existing']}")
    console.print(f"   Graph now: {builder.G.number_of_nodes()} nodes, "
                  f"{builder.G.number_of_edges()} edges")


def cmd_analyze(
    source: str = "",
    community_algo: str = "leiden",
    impact_algo: str = "all",
    resolution: float = 1.0,
    top_n: int = 20,
    output_format: str = "markdown",
    output: str = "",
) -> None:
    """Run graph analysis: impact, communities, actors.

    Args:
        source: Source tag (e.g. 'coc', 'zotero', empty for all).
        community_algo: louvain | leiden | label_propagation.
        impact_algo: degree | pagerank | hits | betweenness | all.
        resolution: Community detection resolution (>1 = finer).
        top_n: Results per section.
        output_format: markdown | json.
        output: Save report to file path.
    """
    from hfpapers.graph import GraphBuilder

    G = GraphBuilder.load()
    if G is None:
        console.print("[yellow]⚠️  No graph cache. Run 'hfpclawer graph build' first.[/yellow]")
        raise SystemExit(1)

    if not source:
        # Auto-detect
        sources_found = set()
        for _, d in G.nodes(data=True):
            src = d.get("sources", set())
            if isinstance(src, str):
                src = {src}
            sources_found.update(s.lower().strip() for s in src if isinstance(s, str))
        if "coc" in sources_found:
            source = "coc"
        else:
            source = "all"

    console.print(f"[bold cyan]🔍 Analyzing graph (source={source}, format={output_format})[/bold cyan]")

    from hfpapers.graph.analyze import Analyzer

    analyzer = Analyzer(G)
    report = analyzer.run(
        source=source,
        impact_algorithm=impact_algo,
        community_algorithm=community_algo,
        resolution=resolution,
        top_n=top_n,
        output_format=output_format,
        output_path=output,
    )

    if output_format == "qmd":
        qmd_path = output or f"~/data/kg/{source}-report.qmd"
        console.print(f"\n[green]✅ QMD + figures generated[/green]")
        console.print(f"   📄 {qmd_path}")
        console.print(f"   🖼️  Figures: {Path(qmd_path).expanduser().parent / 'figures'}")
        console.print(f"\n   [dim]Next: quarto render {qmd_path}[/dim]")
    else:
        console.print(report)


def cmd_step(
    layer: str = "",
    all_layers: bool = False,
    show_config: bool = False,
) -> None:
    """Run stepping citation expansion (multi-layer BFS).

    Args:
        layer: Single layer name to run (e.g. 'QED-foundations').
        all_layers: If True, run all configured layers.
        show_config: If True, show current stepping config and exit.
    """
    from hfpapers.graph.stepping import SteppingExpander, _find_config

    stepper = SteppingExpander(config_path=_find_config())

    if show_config:
        console.print("[bold cyan]📋 Stepping Config[/bold cyan]")
        console.print(stepper.config)
        return

    if not layer and not all_layers:
        console.print("[yellow]Specify --layer NAME or --all[/yellow]")
        console.print("  hfpclawer graph step --layer QED-foundations")
        console.print("  hfpclawer graph step --all")
        console.print("  hfpclawer graph step --show-config")
        return

    if all_layers:
        console.print("[bold cyan]🔄 Running all stepping layers...[/bold cyan]")
        G, layer_stats = stepper.run_all()
    else:
        console.print(f"[bold cyan]🔄 Running layer: {layer}[/bold cyan]")
        result = stepper.run_layer(layer)
        layer_stats = {layer: result}

    # Save the expanded graph
    from hfpapers.graph import GraphBuilder
    builder = GraphBuilder()
    builder.G = stepper.G
    builder.save()

    # Report
    console.print(f"[green]✅ Stepping complete[/green]")
    for lname, stats in layer_stats.items():
        papers = stats.get("papers_found", 0)
        edges = stats.get("edges_added", 0)
        api = stats.get("api_calls", 0)
        console.print(f"  Layer '{lname}': +{papers} papers, +{edges} edges ({api} API calls)")

    full = stepper.stats()
    console.print(f"\n  Graph total: {full['papers']} papers, {full['edges']} edges")
    console.print(f"  Completed layers: {full['layers_completed']}")
