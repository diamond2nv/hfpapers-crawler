#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hfpclawer graph CLI subcommand.

Registered as ``hfpclawer graph {build, stats, export, person, community, path}``.
"""

from __future__ import annotations

import logging
import os

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


def cmd_viz(style: str = "circos", output: str = "") -> None:
    """Generate graph visualization (Circos / spring).

    Args:
        style: 'circos' (default) for Circos plot, 'spring' for spring layout.
        output: Output image path (default: ~/data/kg/circos.png).
    """
    _, G = _load_builder()

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
    else:
        console.print(f"[red]❌ Unknown viz style: '{style}'. Use 'circos'.[/red]")
