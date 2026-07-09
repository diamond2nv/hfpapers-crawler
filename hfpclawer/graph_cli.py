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

    Args:
        person_id: Node ID (e.g. ``person:li-shen`` or just ``li-shen``).
        depth: Ego network radius.
        top_n: Max ego network nodes to list.
    """
    builder, G = _load_builder()

    # Normalize: add "person:" prefix if missing
    nid = person_id if ":" in person_id else f"person:{person_id}"
    if nid not in G:
        console.print(f"[red]❌ Person '{nid}' not found in graph.[/red]")
        # Try fuzzy search
        matches = [n for n in G.nodes if "person:" in n and person_id.lower() in n.lower()]
        if matches:
            console.print(f"[dim]Did you mean: {', '.join(matches[:5])}?[/dim]")
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
            console.print(f"   • {nb_data.get('label', nb)}  [dim]({nt}: {nb})[/dim]")


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
