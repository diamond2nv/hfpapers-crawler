#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hfpclawer graph CLI subcommand.

Registered as ``hfpclawer graph {build, stats, export}``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

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

    builder = GraphBuilder()
    try:
        G = _load_latest_graph()
        if G is None:
            console.print("[yellow]⚠️  No graph built yet. Run 'hfpclawer graph build' first.[/yellow]")
            return
        builder.stats(G)
    except Exception as e:
        console.print(f"[red]❌ Stats failed: {e}[/red]")


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

    G = _load_latest_graph()
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


def _load_latest_graph():
    """Load the most recently built graph from marker metadata.

    Returns the built graph if available, None otherwise.
    For v0.10.0 this is a placeholder — we rebuild each time.
    """
    # For now, return None to trigger on-the-fly build.
    # Phase 2: store graph as pickle/GraphML for fast reload.
    return None
